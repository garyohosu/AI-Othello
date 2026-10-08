"""devloop の安全装置: パス検証、変更の分類、テストコマンドの許可判定。"""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
import sys
from dataclasses import dataclass, field

INSTRUCTION_RE = re.compile(r"^Instruction(\d{5})\.md$")

DEFAULT_PROTECTED_PATHS = [
    # 依存関係
    "requirements*.txt", "**/requirements*.txt", "pyproject.toml", "setup.py", "setup.cfg",
    "Pipfile", "Pipfile.lock", "poetry.lock", "uv.lock",
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "**/package.json",
    "go.mod", "go.sum", "Cargo.toml", "Cargo.lock", "Gemfile", "Gemfile.lock",
    # CI・デプロイ・秘密情報
    ".github/**", ".gitlab-ci.yml", "Dockerfile", "docker-compose*.yml",
    ".env", ".env.*", "**/.env", "*.pem", "*.key",
    # devloop 自身の設定
    "tools/devloop/**",
]

DEFAULT_ALLOWED_TEST_EXECUTABLES = ["py", "python", "python3", "pytest"]


class SafetyError(ValueError):
    """安全上の理由で処理を続けられない。"""


def _is_link_or_junction(path: str) -> bool:
    if os.path.islink(path):
        return True
    is_junction = getattr(os.path, "isjunction", None)
    return bool(is_junction and is_junction(path))


def safe_repo_path(repo: str, rel: str) -> str:
    """リポジトリ内の相対パスを検証して絶対パスを返す。

    絶対パス、ドライブ指定、`..`、リポジトリ外を指すリンク、途中のシンボリックリンク・
    ジャンクションを拒否する。
    """
    if not rel or os.path.isabs(rel) or re.match(r"^[A-Za-z]:", rel) or rel.startswith(("\\", "/")):
        raise SafetyError(f"リポジトリ内の相対パスではない: {rel!r}")
    parts = re.split(r"[\\/]", rel)
    if any(p in ("..", "") for p in parts):
        raise SafetyError(f"パスに .. や空の要素がある: {rel!r}")
    repo_real = os.path.realpath(repo)
    cur = repo_real
    for part in parts:
        cur = os.path.join(cur, part)
        if os.path.lexists(cur) and _is_link_or_junction(cur):
            raise SafetyError(f"シンボリックリンク・ジャンクション経由のパスは使えない: {rel!r}")
    target = os.path.realpath(os.path.join(repo_real, *parts))
    if os.path.commonpath([repo_real, target]) != repo_real:
        raise SafetyError(f"リポジトリ外を指している: {rel!r}")
    return target


def instruction_number(rel: str, instructions_dir: str) -> int:
    """`instructions/Instruction00003.md` から 3 を取り出す。形式が違えば SafetyError。"""
    norm = rel.replace("\\", "/")
    directory, _, name = norm.rpartition("/")
    if directory != instructions_dir.replace("\\", "/").strip("/"):
        raise SafetyError(f"指示書は {instructions_dir}/ 直下に置く: {rel!r}")
    m = INSTRUCTION_RE.match(name)
    if not m:
        raise SafetyError(f"指示書の名前は InstructionNNNNN.md（5桁）: {rel!r}")
    return int(m.group(1))


def instruction_rel(instructions_dir: str, n: int) -> str:
    return f"{instructions_dir.strip('/')}/Instruction{n:05d}.md"


def result_rel(instructions_dir: str, n: int) -> str:
    return f"{instructions_dir.strip('/')}/Result{n:05d}.md"


@dataclass
class ChangeReport:
    changed: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    protected: list[str] = field(default_factory=list)

    @property
    def forbidden(self) -> list[str]:
        return [f"削除: {p}" for p in self.deleted] + [f"保護対象の変更: {p}" for p in self.protected]


def _matches(path: str, patterns: list[str]) -> bool:
    path = path.replace("\\", "/")
    return any(fnmatch.fnmatchcase(path, pat) for pat in patterns)


def classify_changes(
    entries: list[tuple[str, str]],
    protected: list[str],
    allow_delete: bool,
    ignore_prefixes: tuple[str, ...] = (),
) -> ChangeReport:
    """git status の (状態コード, パス) を、通常の変更・削除・保護対象に分ける。"""
    report = ChangeReport()
    for code, path in entries:
        if any(path.replace("\\", "/").startswith(p) for p in ignore_prefixes):
            continue
        report.changed.append(path)
        if not allow_delete and ("D" in code or "R" in code):
            report.deleted.append(path)
        if _matches(path, protected):
            report.protected.append(path)
    return report


def check_test_command(argv: list[str], allowed: list[str]) -> list[str]:
    """設定ファイルに書かれたテストコマンドだけを、許可された実行ファイルで実行する。

    {python} は実行中の Python に置き換える。シェルは使わない。
    """
    if not argv or not all(isinstance(a, str) for a in argv):
        raise SafetyError(f"テストコマンドは文字列の配列にする: {argv!r}")
    argv = [a.replace("{python}", sys.executable) for a in argv]
    exe = argv[0]
    stem = os.path.splitext(os.path.basename(exe))[0].lower()
    allowed_stems = {os.path.splitext(os.path.basename(a))[0].lower() for a in allowed}
    if exe != sys.executable and stem not in allowed_stems:
        raise SafetyError(f"許可されていないテストコマンド: {exe}（許可: {', '.join(sorted(allowed_stems))}）")
    resolved = shutil.which(exe)
    if resolved is None:
        raise SafetyError(f"テストコマンドが見つからない: {exe}")
    return [resolved] + argv[1:]
