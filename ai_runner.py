"""AI CLI の呼び出し、出力解析、タイムアウト処理。

1回の試行ごとに独立したプロセスを起動し、会話履歴は引き継がない。
subprocess には引数リストを渡し、shell=True は使わない。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import game

COMMON_INSTRUCTION = (
    "あなたはオセロのプレイヤーです。提示された8×8の盤面を読み、指定された色として"
    "標準オセロの合法手を1つ選んでください。着手可能な場所がない場合のみPASSを返してください。"
    "回答はA1～H8の座標1つ、またはPASSのみ。説明や装飾は付けないでください。"
)

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

ANSWER_RE =re.compile(r"^(?:[A-H][1-8]|PASS)$")

KNOWN_PROVIDERS = {"mock", "cli"}
SANDBOX_VALUES = {"restricted", "unrestricted", "unknown"}

# 技術エラー種別
TIMEOUT = "timeout"
NONZERO_EXIT = "nonzero_exit"
AUTH = "auth"
LAUNCH = "launch"
PARSE = "parse"

AUTH_PATTERNS = re.compile(
    r"unauthori[sz]ed|authenticat|not logged in|login required|invalid api key|api key not|401",
    re.IGNORECASE,
)

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"xai-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{10,}"),
]
SECRET_ENV_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD", re.IGNORECASE)


class ConfigError(ValueError):
    """モデル設定の不備。"""


@dataclass
class ModelConfig:
    id: str
    provider: str
    model: str
    command: list[str]
    timeout_sec: float | None = None
    enabled: bool = True
    output: str = "text"  # text | json
    json_field: str | None = None  # 例: "result"
    usage_fields: dict[str, str] = field(default_factory=dict)
    version_command: list[str] | None = None
    sandbox: str = "unknown"  # restricted | unrestricted | unknown
    sandbox_note: str | None = None
    env: dict[str, str] = field(default_factory=dict)  # 追加の環境変数（認証情報は不可）

    @property
    def prompt_via(self) -> str:
        """プロンプトの渡し方。command 内のプレースホルダで決まる。"""
        joined = " ".join(self.command)
        if "{prompt_file}" in joined:
            return "file"
        if "{prompt}" in joined:
            return "arg"
        return "stdin"

    @property
    def is_mock(self) -> bool:
        return self.provider == "mock"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelConfig":
        missing = [k for k in ("id", "provider", "model", "command") if not data.get(k)]
        if missing:
            raise ConfigError(f"必須項目がない: {', '.join(missing)} ({data.get('id', '?')})")
        if data["provider"] not in KNOWN_PROVIDERS:
            raise ConfigError(f"未知の provider: {data['provider']} ({data['id']})")
        command = data["command"]
        if not isinstance(command, list) or not all(isinstance(x, str) for x in command):
            raise ConfigError(f"command は文字列の配列にする ({data['id']})")
        output = data.get("output", "text")
        if output not in ("text", "json"):
            raise ConfigError(f"output は text か json ({data['id']})")
        if output == "json" and not data.get("json_field"):
            raise ConfigError(f"output: json には json_field が必要 ({data['id']})")
        sandbox = data.get("sandbox", "restricted" if data["provider"] == "mock" else "unknown")
        if sandbox not in SANDBOX_VALUES:
            raise ConfigError(f"sandbox は {sorted(SANDBOX_VALUES)} のいずれか ({data['id']})")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._\-]*", str(data["id"])):
            raise ConfigError(f"id は英数字と . _ - のみ: {data['id']!r}")
        joined = " ".join(command)
        if "{prompt}" in joined and "{prompt_file}" in joined:
            raise ConfigError(f"{{prompt}} と {{prompt_file}} は同時に使えない ({data['id']})")
        env = data.get("env") or {}
        if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
            raise ConfigError(f"env は文字列から文字列への対応にする ({data['id']})")
        secret_like = [k for k in env if SECRET_ENV_NAME.search(k)]
        if secret_like:
            raise ConfigError(
                f"env に認証情報らしき変数は書かない: {', '.join(secret_like)} ({data['id']})。"
                "OSの環境変数か各CLIのログイン状態を使う"
            )
        return cls(
            id=str(data["id"]),
            provider=data["provider"],
            model=str(data["model"]),
            command=list(command),
            timeout_sec=data.get("timeout_sec"),
            enabled=bool(data.get("enabled", True)),
            output=output,
            json_field=data.get("json_field"),
            usage_fields=dict(data.get("usage_fields") or {}),
            version_command=data.get("version_command"),
            sandbox=sandbox,
            sandbox_note=data.get("sandbox_note"),
            env=dict(env),
        )


def load_models(data: dict[str, Any]) -> list[ModelConfig]:
    items = (data or {}).get("models") or []
    models = [ModelConfig.from_dict(m) for m in items]
    seen: set[str] = set()
    for m in models:
        if m.id in seen:
            raise ConfigError(f"id が重複している: {m.id}")
        seen.add(m.id)
    return models


def build_prompt(board_text: str, color: str) -> str:
    """全モデル共通のプロンプト。担当色の部分だけを切り替える。"""
    return (
        f"{COMMON_INSTRUCTION}\n"
        "\n"
        f"あなたの色: {game.COLOR_NAME_JA[color]}（{game.STONE[color]}）\n"
        f"記号: {game.BLACK_STONE}=黒、{game.WHITE_STONE}=白、{game.EMPTY}=空き\n"
        "座標規則: 列は左からA～H、行は上から1～8。例: 左上がA1、右下がH8。\n"
        "\n"
        "盤面:\n"
        f"{board_text}"
    )


def mask_secrets(text: str | None) -> str | None:
    if not text:
        return text
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(lambda m: (m.group(1) if m.groups() else "") + "***MASKED***", text)
    for name, value in os.environ.items():
        if SECRET_ENV_NAME.search(name) and value and len(value) >= 8 and value in text:
            text = text.replace(value, "***MASKED***")
    return text


def classify_answer(answer: str) -> str:
    """'move' / 'pass' / 'format' を返す（合法性はここでは判定しない）。"""
    if not ANSWER_RE.fullmatch(answer):
        return "format"
    return "pass" if answer == "PASS" else "move"


def _dig(data: Any, path: str) -> Any:
    cur = data
    for key in path.split("."):
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        elif isinstance(cur, list) and key.isdigit() and int(key) < len(cur):
            cur = cur[int(key)]
        else:
            raise KeyError(path)
    return cur


@dataclass
class Extracted:
    body: str | None
    error: str | None = None  # parse エラー時の説明
    meta: dict[str, Any] = field(default_factory=dict)


def extract_body(stdout: str, cfg: ModelConfig) -> Extracted:
    """CLI出力から回答本文を取り出し、前後の空白・改行を除去する。

    本文から座標を探し出すことはしない。
    """
    meta: dict[str, Any] = {}
    if cfg.output == "text":
        return Extracted(body=stdout.strip(), meta=meta)
    try:
        data = json.loads(stdout)
        body = _dig(data, cfg.json_field or "")
    except (json.JSONDecodeError, KeyError) as exc:
        return Extracted(body=None, error=f"構造化出力から本文を取り出せない: {exc}")
    if not isinstance(body, str):
        return Extracted(body=None, error=f"本文フィールドが文字列ではない: {type(body).__name__}")
    for key, path in cfg.usage_fields.items():
        try:
            meta[key] = _dig(data, path)
        except KeyError:
            meta[key] = None
    return Extracted(body=body.strip(), meta=meta)


@dataclass
class CliResult:
    stdout: str
    stderr: str
    exit_code: int | None
    elapsed_sec: float
    error_type: str | None = None
    error_detail: str | None = None
    retry_after_sec: float | None = None


def resolve_command(
    command: list[str],
    model: str,
    prompt: str | None = None,
    prompt_file: str | None = None,
) -> list[str]:
    """プレースホルダを置換し、実行ファイルを shutil.which で解決する。

    Windows の npm 製 CLI は .cmd ラッパーなので、shell=True を使わずに
    起動するには実体パスへの解決が必要。.cmd / .bat に {prompt} で
    プロンプトを引数として渡すと cmd.exe の引数解釈で壊れたり注入の
    危険があるため拒否する（標準入力か {prompt_file} を使う）。
    """
    exe = shutil.which(command[0].replace("{python}", sys.executable))
    if exe is None:
        raise FileNotFoundError(f"コマンドが見つからない: {command[0]}")
    if any("{prompt}" in part for part in command[1:]) and os.path.splitext(exe)[1].lower() in (".cmd", ".bat"):
        raise ConfigError(f"{exe} は .cmd/.bat なので {{prompt}} で引数として渡せない")
    argv = [exe]
    for part in command[1:]:
        part = (
            part.replace("{model}", model)
            .replace("{python}", sys.executable)
            .replace("{project}", PROJECT_ROOT)
        )
        if prompt_file is not None:
            part = part.replace("{prompt_file}", prompt_file)
        if prompt is not None:
            part = part.replace("{prompt}", prompt)
        argv.append(part)
    return argv


def _kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        proc.kill()
    except OSError:
        pass


def run_cli(
    argv: list[str],
    stdin_text: str,
    timeout_sec: float,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> CliResult:
    """CLIを1回実行する。stdin_text を標準入力に渡す（空なら空入力）。"""
    start = time.monotonic()
    kwargs: dict[str, Any] = {}
    if env:
        kwargs["env"] = {**os.environ, **env}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            **kwargs,
        )
    except OSError as exc:
        return CliResult("", "", None, time.monotonic() - start, LAUNCH, str(exc))
    try:
        stdout, stderr = proc.communicate(stdin_text, timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except (subprocess.TimeoutExpired, ValueError):
            stdout, stderr = "", ""
        return CliResult(
            stdout or "", stderr or "", None, time.monotonic() - start, TIMEOUT,
            f"{timeout_sec}秒以内に応答がない",
        )
    except BaseException:
        # Ctrl+C などでも子プロセスを残さない
        _kill_tree(proc)
        raise
    elapsed = time.monotonic() - start
    if proc.returncode != 0:
        kind = AUTH if AUTH_PATTERNS.search(stderr or "") else NONZERO_EXIT
        return CliResult(stdout, stderr, proc.returncode, elapsed, kind, f"終了コード {proc.returncode}")
    return CliResult(stdout, stderr, 0, elapsed)


@dataclass
class Attempt:
    """1回の試行の結果（合法性判定の前段階まで）。"""

    prompt: str
    raw_stdout: str
    raw_stderr: str
    exit_code: int | None
    elapsed_sec: float
    answer: str | None  # 抽出・空白除去後の本文。技術エラー時は None
    error_type: str | None = None
    error_detail: str | None = None
    retry_after_sec: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    board_delivery: str = "inline"
    prompt_via: str = "stdin"


class AIPlayer:
    def __init__(self, cfg: ModelConfig, default_timeout_sec: float = 120.0, cwd: str | None = None):
        self.cfg = cfg
        self.timeout_sec = float(cfg.timeout_sec or default_timeout_sec)
        self.cwd = cwd
        self._cli_version: str | None | bool = False  # False = 未取得

    @property
    def id(self) -> str:
        return self.cfg.id

    def cli_version(self) -> str | None:
        """version_command の出力（取得できなければ None）。課金のない呼び出しのみ。"""
        if self._cli_version is not False:
            return self._cli_version  # type: ignore[return-value]
        version: str | None = None
        if self.cfg.version_command:
            try:
                argv = resolve_command(self.cfg.version_command, self.cfg.model)
                res = run_cli(argv, "", 30, cwd=self.cwd, env=self.cfg.env)
                if res.error_type is None:
                    version = (res.stdout.strip() or res.stderr.strip()).splitlines()[0][:200] or None
            except (FileNotFoundError, IndexError, ConfigError):
                version = None
        self._cli_version = version
        return version

    def ask(self, board_text: str, color: str) -> Attempt:
        prompt = build_prompt(board_text, color)
        via = self.cfg.prompt_via
        prompt_file = None
        if via == "file":
            # 作業ディレクトリ（対局ごとの workdir）にプロンプトを書いて渡す
            prompt_file = os.path.abspath(os.path.join(self.cwd or ".", "prompt.txt"))
            with open(prompt_file, "w", encoding="utf-8", newline="\n") as f:
                f.write(prompt)
        try:
            argv = resolve_command(self.cfg.command, self.cfg.model, prompt=prompt, prompt_file=prompt_file)
        except (FileNotFoundError, ConfigError) as exc:
            return Attempt(prompt, "", "", None, 0.0, None, LAUNCH, str(exc), prompt_via=via)
        stdin_text = prompt if via == "stdin" else ""
        res = run_cli(argv, stdin_text, self.timeout_sec, cwd=self.cwd, env=self.cfg.env)
        stdout = mask_secrets(res.stdout) or ""
        stderr = mask_secrets(res.stderr) or ""
        if res.error_type:
            return Attempt(
                prompt, stdout, stderr, res.exit_code, res.elapsed_sec, None,
                res.error_type, res.error_detail, res.retry_after_sec, prompt_via=via,
            )
        ext = extract_body(res.stdout, self.cfg)
        if ext.body is None:
            return Attempt(prompt, stdout, stderr, res.exit_code, res.elapsed_sec, None, PARSE, ext.error,
                           prompt_via=via)
        return Attempt(prompt, stdout, stderr, res.exit_code, res.elapsed_sec, ext.body, meta=ext.meta,
                       prompt_via=via)
