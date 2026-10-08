"""読み取り専用の Git 操作。コントローラは commit / push / checkout などを一切しない。"""

from __future__ import annotations

import hashlib
import os
import subprocess

READ_ONLY_SUBCOMMANDS = {"rev-parse", "status", "diff", "ls-files"}


class GitError(RuntimeError):
    pass


def git(repo: str, *args: str) -> str:
    if not args or args[0] not in READ_ONLY_SUBCOMMANDS:
        raise GitError(f"読み取り専用以外の git 操作は使わない: {args[:1]}")
    try:
        res = subprocess.run(
            ["git", "-C", repo, *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitError(f"git {args[0]} を実行できない: {exc}") from exc
    if res.returncode != 0:
        raise GitError(f"git {' '.join(args)} が失敗: {res.stderr.strip()}")
    return res.stdout


def toplevel(repo: str) -> str:
    return git(repo, "rev-parse", "--show-toplevel").strip()


def head(repo: str) -> str | None:
    try:
        return git(repo, "rev-parse", "--verify", "HEAD").strip()
    except GitError:
        return None


def status_entries(repo: str) -> list[tuple[str, str]]:
    """(2文字の状態コード, パス) の一覧。未追跡ファイルも個別に含む。"""
    out = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    entries: list[tuple[str, str]] = []
    items = out.split("\0")
    i = 0
    while i < len(items):
        item = items[i]
        if not item:
            i += 1
            continue
        code, path = item[:2], item[3:]
        entries.append((code, path))
        if "R" in code or "C" in code:
            i += 1  # 移動元のパスが続く
            if i < len(items) and items[i]:
                entries.append(("D ", items[i]))
        i += 1
    return entries


def diff_text(repo: str, base: str | None, max_chars: int, exclude: str = ".devloop") -> str:
    """base からの差分（作業ツリー）と未追跡ファイルの一覧。長すぎる場合は切り詰める。"""
    spec = ["--", ".", f":(exclude){exclude}"]
    parts = []
    if base:
        parts.append(git(repo, "diff", "--no-color", "--no-ext-diff", base, *spec))
    untracked = git(repo, "ls-files", "--others", "--exclude-standard", *spec)
    if untracked.strip():
        parts.append("# 未追跡ファイル\n" + untracked)
    text = "\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n...（{len(text) - max_chars}文字を省略）\n"
    return text


def snapshot(repo: str, exclude: str = ".devloop") -> str:
    """作業ツリーの状態のハッシュ（HEAD・status・差分・未追跡ファイルの内容）。

    レビュー担当がファイルを変えていないかの検出に使う。exclude（コントローラ自身の
    状態ディレクトリ）は対象外。
    """
    spec = ["--", ".", f":(exclude){exclude}"]
    h = hashlib.sha256()
    h.update((head(repo) or "").encode())
    h.update(git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all", *spec).encode("utf-8"))
    h.update(git(repo, "diff", "--no-color", "--no-ext-diff", *spec).encode("utf-8"))
    for rel in sorted(git(repo, "ls-files", "--others", "--exclude-standard", *spec).splitlines()):
        h.update(rel.encode("utf-8"))
        try:
            with open(os.path.join(repo, rel), "rb") as f:
                h.update(hashlib.sha256(f.read()).digest())
        except OSError:
            h.update(b"<unreadable>")
    return h.hexdigest()
