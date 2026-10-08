"""レビュー担当AIが返すJSONの検証。

形式が少しでも違えば ReviewSchemaError とし、コントローラは判定不能として停止する。
説明文の中からJSONを探し出すことはしない（出力全体が1つのJSONオブジェクトであること）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

DECISIONS = ("complete", "retry", "blocked")
MAX_SUMMARY = 4000
MAX_ISSUES = 30
MAX_ISSUE_LEN = 2000
MAX_NEXT_INSTRUCTION = 30000

# Codex の --output-schema などに渡せる JSON Schema（strict 形式: 全項目必須・追加項目なし）
REVIEW_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["decision", "summary", "issues", "next_instruction"],
    "properties": {
        "decision": {"type": "string", "enum": list(DECISIONS)},
        "summary": {"type": "string", "maxLength": MAX_SUMMARY},
        "issues": {
            "type": "array",
            "maxItems": MAX_ISSUES,
            "items": {"type": "string", "maxLength": MAX_ISSUE_LEN},
        },
        "next_instruction": {"type": ["string", "null"], "maxLength": MAX_NEXT_INSTRUCTION},
    },
}


class ReviewSchemaError(ValueError):
    """レビュー結果が規定の形式ではない。"""


@dataclass(frozen=True)
class Review:
    decision: str
    summary: str
    issues: tuple[str, ...]
    next_instruction: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "summary": self.summary,
            "issues": list(self.issues),
            "next_instruction": self.next_instruction,
        }


def validate_review(obj: Any) -> Review:
    if not isinstance(obj, dict):
        raise ReviewSchemaError("JSONオブジェクトではない")
    expected = set(REVIEW_JSON_SCHEMA["required"])
    keys = set(obj)
    if keys != expected:
        missing, extra = expected - keys, keys - expected
        raise ReviewSchemaError(f"項目が規定と違う（不足: {sorted(missing)}, 余分: {sorted(extra)}）")
    decision = obj["decision"]
    if decision not in DECISIONS:
        raise ReviewSchemaError(f"decision が不正: {decision!r}")
    summary = obj["summary"]
    if not isinstance(summary, str) or len(summary) > MAX_SUMMARY:
        raise ReviewSchemaError("summary は4000文字以内の文字列")
    issues = obj["issues"]
    if (
        not isinstance(issues, list)
        or len(issues) > MAX_ISSUES
        or not all(isinstance(i, str) and len(i) <= MAX_ISSUE_LEN for i in issues)
    ):
        raise ReviewSchemaError("issues は文字列の配列（30件以内、各2000文字以内）")
    nxt = obj["next_instruction"]
    if nxt is not None and (not isinstance(nxt, str) or len(nxt) > MAX_NEXT_INSTRUCTION):
        raise ReviewSchemaError("next_instruction は30000文字以内の文字列か null")
    if decision == "retry" and not (isinstance(nxt, str) and nxt.strip()):
        raise ReviewSchemaError("retry のときは next_instruction が必要")
    return Review(decision, summary, tuple(issues), nxt)


def parse_review(text: str) -> Review:
    """出力全体（前後の空白を除く）が1つのJSONオブジェクトである場合だけ受け付ける。"""
    stripped = (text or "").strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        raise ReviewSchemaError("出力全体が1つのJSONオブジェクトではない")
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ReviewSchemaError(f"JSONとして読めない: {exc}") from exc
    return validate_review(obj)
