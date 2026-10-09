"""監督ランナー専用の限定された Git 書き込み操作。

コントローラ本体（controller.py）は commit / push をしない。このモジュールは監督ランナー（autopilot.py）からだけ使う。
許可する操作は次のものに限る: stage（パス指定の git add）、commit（メッセージは標準入力で渡す）、push（ブランチ指定・強制なし）。
main / master への commit・push は拒否する。
"""

from __future__ import annotations

import subprocess

from . import gitutil

PROTECTED_BRANCHES = {"main", "master"}
TRAILER_KEY = "Devloop-Instruction:"


class GitWriteError(RuntimeError):
    pass


def _run(repo: str, *args: str, stdin_text: str | None = None) -> str:
    try:
        res = subprocess.run(
            ["git", "-C", repo, *args],
            input=stdin_text.encode("utf-8") if stdin_text is not None else None,
            capture_output=True, timeout=120, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitWriteError(f"git {args[0]} を実行できない: {exc}") from exc
    if res.returncode != 0:
        raise GitWriteError(f"git {args[0]} が失敗: {res.stderr.decode('utf-8', errors='replace').strip()}")
    return res.stdout.decode("utf-8", errors="replace")


def current_branch(repo: str) -> str:
    return gitutil.git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()


def is_protected(branch: str) -> bool:
    return branch in PROTECTED_BRANCHES or branch in ("HEAD", "")


def stage(repo: str, paths: list[str]) -> None:
    if not paths:
        raise GitWriteError("stage するパスがない")
    for p in paths:
        if p.startswith("-") or p.startswith("/") or ".." in p.replace("\\", "/").split("/"):
            raise GitWriteError(f"危険なパスは stage しない: {p}")
    _run(repo, "add", "--", *paths)


def staged_paths(repo: str) -> list[str]:
    out = gitutil.git(repo, "diff", "--cached", "--name-only", "-z")
    return sorted(p for p in out.split("\0") if p)


def commit(repo: str, message: str) -> str:
    if is_protected(current_branch(repo)):
        raise GitWriteError("保護されたブランチには commit しない")
    _run(repo, "commit", "-q", "-F", "-", stdin_text=message)
    return gitutil.git(repo, "rev-parse", "HEAD").strip()


def push(repo: str, remote: str, branch: str) -> None:
    if is_protected(branch):
        raise GitWriteError(f"保護されたブランチへは自動 push しない: {branch}")
    if branch.startswith("-") or remote.startswith("-"):
        raise GitWriteError("ブランチ名・リモート名が不正")
    _run(repo, "push", remote, f"refs/heads/{branch}:refs/heads/{branch}")


def find_trailer_commit(repo: str, instruction: str, limit: int = 300) -> str | None:
    """既にこの指示書の commit があれば、そのSHAを返す（再開時の二重 commit 防止）。"""
    out = gitutil.git(repo, "log", f"-n{limit}", "--format=%H%x1f%B%x1e")
    for record in out.split("\x1e"):
        if "\x1f" not in record:
            continue
        sha, body = record.split("\x1f", 1)
        if f"{TRAILER_KEY} {instruction}" in body:
            return sha.strip()
    return None
