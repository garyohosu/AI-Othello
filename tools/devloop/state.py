"""devloop の状態保存とイベントログ（対象リポジトリの .devloop/ 配下）。"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any

from .adapters import mask_secrets
from .safety import safe_repo_path


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _replace_with_retry(src: str, dst: str, attempts: int = 10, wait_sec: float = 0.05) -> None:
    for i in range(1, attempts + 1):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == attempts:
                raise
            time.sleep(wait_sec * i)


class StateStore:
    """state.json（現在の状態）と log.jsonl（追記のみのイベントログ）を扱う。"""

    def __init__(self, repo: str, state_dir: str = ".devloop"):
        self.dir = safe_repo_path(repo, state_dir)
        self.state_path = os.path.join(self.dir, "state.json")
        self.log_path = os.path.join(self.dir, "log.jsonl")

    def ensure_dir(self) -> None:
        os.makedirs(self.dir, exist_ok=True)

    def load(self) -> dict[str, Any] | None:
        if not os.path.exists(self.state_path):
            return None
        with open(self.state_path, encoding="utf-8") as f:
            return json.load(f)

    def save(self, state: dict[str, Any]) -> None:
        self.ensure_dir()
        state["updated_at"] = now_iso()
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        _replace_with_retry(tmp, self.state_path)

    def log(self, event: str, **data: Any) -> None:
        self.ensure_dir()
        record = {"time": now_iso(), "event": event, **data}
        line = mask_secrets(json.dumps(record, ensure_ascii=False))
        with open(self.log_path, "a", encoding="utf-8", newline="\n") as f:
            f.write(line + "\n")
