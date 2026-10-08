"""実装担当・レビュー担当の起動層。

役割ごとに provider（mock / claude / codex）と command（引数配列）を設定する。
- mock: ローカルのスクリプト。AIは呼ばない。実AIのCLIを mock として登録すると設定エラー。
- claude / codex: 実AI。コントローラが明示的な許可を確認した場合だけ起動する。
subprocess には引数リストを渡し、shell=True は使わない。
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any

PROVIDERS = ("mock", "claude", "codex")
REAL_AI_EXECUTABLES = {"claude", "codex", "gemini", "grok", "openai", "aider", "cursor-agent"}
PLACEHOLDERS = ("{python}", "{prompt}", "{instruction}", "{result}", "{repo}", "{schema_file}", "{model}")

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"xai-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{10,}"),
]
SECRET_ENV_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD", re.IGNORECASE)


class AdapterError(ValueError):
    """役割の設定が不正、または起動できない。"""


@dataclass
class RoleConfig:
    name: str  # implementer / reviewer
    provider: str
    command: list[str]
    timeout_sec: float = 1800.0
    model: str = ""
    note: str = ""

    @property
    def is_real(self) -> bool:
        return self.provider != "mock"

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> "RoleConfig":
        if not isinstance(data, dict):
            raise AdapterError(f"{name} の設定がない")
        provider = data.get("provider")
        if provider not in PROVIDERS:
            raise AdapterError(f"{name}.provider は {PROVIDERS} のいずれか: {provider!r}")
        command = data.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
            raise AdapterError(f"{name}.command は文字列の配列にする")
        timeout = float(data.get("timeout_sec", 1800))
        if timeout <= 0:
            raise AdapterError(f"{name}.timeout_sec は正の数")
        role = cls(name, provider, list(command), timeout, str(data.get("model", "")), str(data.get("note", "")))
        if provider == "mock" and _looks_like_real_ai(command[0]):
            raise AdapterError(f"{name}: 実AIのCLI（{command[0]}）を mock として登録することはできない")
        return role


def _looks_like_real_ai(exe: str) -> bool:
    stem = os.path.splitext(os.path.basename(exe.replace("{python}", "")))[0].lower()
    return stem in REAL_AI_EXECUTABLES


def mask_secrets(text: str) -> str:
    if not text:
        return text
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(lambda m: (m.group(1) if m.groups() else "") + "***MASKED***", text)
    for name, value in os.environ.items():
        if SECRET_ENV_NAME.search(name) and value and len(value) >= 8 and value in text:
            text = text.replace(value, "***MASKED***")
    return text


def resolve_argv(command: list[str], values: dict[str, str]) -> tuple[list[str], bool]:
    """プレースホルダを置換し、実行ファイルを shutil.which で解決する。

    戻り値の bool は、プロンプトを引数で渡すか（{prompt} を含むか）。含まなければ標準入力で渡す。
    Windows の .cmd / .bat に {prompt} を渡すと cmd.exe の引数解釈で壊れるおそれがあるため拒否する。
    """
    exe = shutil.which(command[0].replace("{python}", sys.executable))
    if exe is None:
        raise AdapterError(f"コマンドが見つからない: {command[0]}")
    uses_prompt_arg = any("{prompt}" in part for part in command[1:])
    if uses_prompt_arg and os.path.splitext(exe)[1].lower() in (".cmd", ".bat"):
        raise AdapterError(f"{exe} は .cmd/.bat なので {{prompt}} で引数として渡せない（標準入力を使う）")
    argv = [exe]
    for part in command[1:]:
        for key in PLACEHOLDERS:
            name = key.strip("{}")
            if key == "{python}":
                part = part.replace(key, sys.executable)
            elif name in values:
                part = part.replace(key, values[name])
        argv.append(part)
    return argv, uses_prompt_arg


@dataclass
class ProcResult:
    argv: list[str]
    stdout: str
    stderr: str
    exit_code: int | None
    elapsed_sec: float
    timed_out: bool = False
    launch_error: str | None = None

    @property
    def ok(self) -> bool:
        return not self.timed_out and self.launch_error is None and self.exit_code == 0

    def describe_error(self) -> str | None:
        if self.launch_error:
            return f"起動失敗: {self.launch_error}"
        if self.timed_out:
            return "タイムアウト"
        if self.exit_code != 0:
            return f"非ゼロ終了: {self.exit_code}"
        return None


def _kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        proc.kill()
    except OSError:
        pass


def run_process(argv: list[str], stdin_text: str, timeout_sec: float, cwd: str) -> ProcResult:
    """プロセスを1回実行する。タイムアウト・Ctrl+C ではプロセスツリーごと終了させる。"""
    start = time.monotonic()
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8", errors="replace", cwd=cwd, **kwargs,
        )
    except OSError as exc:
        return ProcResult(argv, "", "", None, time.monotonic() - start, launch_error=str(exc))
    try:
        stdout, stderr = proc.communicate(stdin_text, timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except (subprocess.TimeoutExpired, ValueError):
            stdout, stderr = "", ""
        return ProcResult(argv, stdout or "", stderr or "", None, time.monotonic() - start, timed_out=True)
    except BaseException:
        _kill_tree(proc)
        raise
    return ProcResult(argv, stdout, stderr, proc.returncode, time.monotonic() - start)


def run_role(role: RoleConfig, prompt: str, values: dict[str, str], cwd: str) -> ProcResult:
    """役割のコマンドを1回実行する。{prompt} がなければプロンプトは標準入力で渡す。"""
    try:
        argv, prompt_as_arg = resolve_argv(role.command, {**values, "prompt": prompt, "model": role.model})
    except AdapterError as exc:
        return ProcResult(role.command, "", "", None, 0.0, launch_error=str(exc))
    res = run_process(argv, "" if prompt_as_arg else prompt, role.timeout_sec, cwd)
    res.stdout = mask_secrets(res.stdout)
    res.stderr = mask_secrets(res.stderr)
    return res
