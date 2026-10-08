"""対局結果の CSV 集計。

- 技術中断は勝率の分母に含めず、別に数える。
- 反則負けの対局は勝敗には含めるが、石差の集計からは除く。
- 平均応答時間は、CLIから回答本文を取得できた試行（合法手・PASS・反則回答）の平均。
- トークン・費用は取得できた値だけを合計し、取得できた対局数を併記する。
"""

from __future__ import annotations

import csv
import os
from typing import Any

from game import BLACK, WHITE, opponent
from tournament import (
    FINISHED,
    IN_PROGRESS,
    RESULT_FOUL_LOSS,
    RESULT_NORMAL,
    TECHNICAL_ABORT,
    GameStore,
    replace_with_retry,
    tournaments_dir,
)

MATCH_COLUMNS = [
    "tournament_id", "game_id", "black", "white", "result_type", "winner", "loser",
    "black_stones", "white_stones", "stone_diff", "moves",
    "black_fouls", "white_fouls",
    "black_foul_format", "black_foul_illegal", "black_foul_wrong_pass",
    "white_foul_format", "white_foul_illegal", "white_foul_wrong_pass",
    "black_tech_errors", "white_tech_errors", "aborted_by",
    "black_avg_sec", "white_avg_sec",
    "black_tokens", "white_tokens", "black_cost_usd", "white_cost_usd",
    "started_at", "finished_at",
]

RANKING_COLUMNS = [
    "model_id", "games", "wins", "losses", "draws", "win_rate",
    "games_black", "win_rate_black", "games_white", "win_rate_white",
    "stone_diff_total", "stone_diff_avg", "stone_diff_games",
    "foul_losses", "fouls_illegal", "fouls_wrong_pass", "fouls_format",
    "avg_response_sec", "response_samples",
    "tech_errors", "tech_error_avg_sec", "tech_aborts",
    "tokens", "tokens_games", "cost_usd", "cost_games",
]


def _game_ids(games_root: str, tournament_id: str | None) -> list[str]:
    if tournament_id:
        from tournament import load_tournament

        return [g["game_id"] for g in load_tournament(games_root, tournament_id)["games"]]
    if not os.path.isdir(games_root):
        return []
    skip = os.path.basename(tournaments_dir(games_root))
    return sorted(
        name for name in os.listdir(games_root)
        if name != skip and os.path.exists(os.path.join(games_root, name, "state.json"))
    )


def load_games(games_root: str, tournament_id: str | None = None) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    result = []
    for gid in _game_ids(games_root, tournament_id):
        store = GameStore(games_root, gid)
        if not store.exists():
            continue
        result.append((store.load_state(), store.read_records()))
    return result


def _side_metrics(records: list[dict[str, Any]], color: str) -> dict[str, Any]:
    mine = [r for r in records if r["color"] == color]
    answered = [r["elapsed_sec"] for r in mine if r["outcome"] in ("move", "pass", "foul")]
    tech = [r["elapsed_sec"] for r in mine if r["outcome"] == "technical_error"]
    tokens = [
        (r.get("input_tokens") or 0) + (r.get("output_tokens") or 0)
        for r in mine
        if r.get("input_tokens") is not None or r.get("output_tokens") is not None
    ]
    costs = [r["cost_usd"] for r in mine if r.get("cost_usd") is not None]
    return {
        "answered_times": answered,
        "tech_times": tech,
        "tokens": sum(tokens) if tokens else None,
        "cost": sum(costs) if costs else None,
    }


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def _result_type(state: dict[str, Any]) -> str:
    if state["status"] == IN_PROGRESS:
        return IN_PROGRESS
    return state["result"]


def build_match_rows(games: list[tuple[dict[str, Any], list[dict[str, Any]]]]) -> list[dict[str, Any]]:
    rows = []
    for state, records in games:
        stones = state.get("stones") or {}
        b, w = _side_metrics(records, BLACK), _side_metrics(records, WHITE)
        winner = state.get("winner")
        loser = state.get("loser")
        fb = state["foul_breakdown"]
        rows.append({
            "tournament_id": state.get("tournament_id") or "",
            "game_id": state["game_id"],
            "black": state["black"],
            "white": state["white"],
            "result_type": _result_type(state),
            "winner": state[winner] if winner else ("draw" if state.get("result") == RESULT_NORMAL else ""),
            "loser": state[loser] if loser else "",
            "black_stones": stones.get(BLACK, ""),
            "white_stones": stones.get(WHITE, ""),
            "stone_diff": stones[BLACK] - stones[WHITE] if stones else "",
            "moves": state["move_number"] - 1,
            "black_fouls": state["fouls"][BLACK],
            "white_fouls": state["fouls"][WHITE],
            "black_foul_format": fb[BLACK]["format"],
            "black_foul_illegal": fb[BLACK]["illegal_move"],
            "black_foul_wrong_pass": fb[BLACK]["wrong_pass"],
            "white_foul_format": fb[WHITE]["format"],
            "white_foul_illegal": fb[WHITE]["illegal_move"],
            "white_foul_wrong_pass": fb[WHITE]["wrong_pass"],
            "black_tech_errors": state["tech_errors"][BLACK],
            "white_tech_errors": state["tech_errors"][WHITE],
            "aborted_by": state[state["aborted_by"]] if state.get("aborted_by") else "",
            "black_avg_sec": _avg(b["answered_times"]),
            "white_avg_sec": _avg(w["answered_times"]),
            "black_tokens": b["tokens"],
            "white_tokens": w["tokens"],
            "black_cost_usd": b["cost"],
            "white_cost_usd": w["cost"],
            "started_at": state.get("created_at"),
            "finished_at": state.get("finished_at"),
        })
    return rows


def _rate(points: float, games: int) -> float | None:
    return round(points / games, 4) if games else None


def build_ranking(games: list[tuple[dict[str, Any], list[dict[str, Any]]]]) -> list[dict[str, Any]]:
    acc: dict[str, dict[str, Any]] = {}

    def entry(model_id: str) -> dict[str, Any]:
        return acc.setdefault(model_id, {
            "model_id": model_id, "games": 0, "wins": 0, "losses": 0, "draws": 0,
            "points": 0.0, "games_black": 0, "points_black": 0.0, "games_white": 0, "points_white": 0.0,
            "stone_diffs": [], "foul_losses": 0, "fouls_illegal": 0, "fouls_wrong_pass": 0,
            "fouls_format": 0, "answered_times": [], "tech_times": [], "tech_aborts": 0,
            "tokens": None, "tokens_games": 0, "cost_usd": None, "cost_games": 0,
        })

    for state, records in games:
        if state["status"] == IN_PROGRESS:
            continue
        for color in (BLACK, WHITE):
            e = entry(state[color])
            fb = state["foul_breakdown"][color]
            e["fouls_illegal"] += fb["illegal_move"]
            e["fouls_wrong_pass"] += fb["wrong_pass"]
            e["fouls_format"] += fb["format"]
            m = _side_metrics(records, color)
            e["answered_times"] += m["answered_times"]
            e["tech_times"] += m["tech_times"]
            if m["tokens"] is not None:
                e["tokens"] = (e["tokens"] or 0) + m["tokens"]
                e["tokens_games"] += 1
            if m["cost"] is not None:
                e["cost_usd"] = (e["cost_usd"] or 0) + m["cost"]
                e["cost_games"] += 1
            if state["status"] == TECHNICAL_ABORT:
                if state.get("aborted_by") == color:
                    e["tech_aborts"] += 1
                continue
            if state["status"] != FINISHED:
                continue
            e["games"] += 1
            e[f"games_{color}"] += 1
            if state["winner"] is None:
                pts = 0.5
                e["draws"] += 1
            elif state["winner"] == color:
                pts = 1.0
                e["wins"] += 1
            else:
                pts = 0.0
                e["losses"] += 1
                if state["result"] == RESULT_FOUL_LOSS:
                    e["foul_losses"] += 1
            e["points"] += pts
            e[f"points_{color}"] += pts
            if state["result"] == RESULT_NORMAL:
                stones = state["stones"]
                e["stone_diffs"].append(stones[color] - stones[opponent(color)])

    rows = []
    for e in acc.values():
        rows.append({
            "model_id": e["model_id"],
            "games": e["games"],
            "wins": e["wins"],
            "losses": e["losses"],
            "draws": e["draws"],
            "win_rate": _rate(e["points"], e["games"]),
            "games_black": e["games_black"],
            "win_rate_black": _rate(e["points_black"], e["games_black"]),
            "games_white": e["games_white"],
            "win_rate_white": _rate(e["points_white"], e["games_white"]),
            "stone_diff_total": sum(e["stone_diffs"]) if e["stone_diffs"] else None,
            "stone_diff_avg": _avg(e["stone_diffs"]),
            "stone_diff_games": len(e["stone_diffs"]),
            "foul_losses": e["foul_losses"],
            "fouls_illegal": e["fouls_illegal"],
            "fouls_wrong_pass": e["fouls_wrong_pass"],
            "fouls_format": e["fouls_format"],
            "avg_response_sec": _avg(e["answered_times"]),
            "response_samples": len(e["answered_times"]),
            "tech_errors": len(e["tech_times"]),
            "tech_error_avg_sec": _avg(e["tech_times"]),
            "tech_aborts": e["tech_aborts"],
            "tokens": e["tokens"],
            "tokens_games": e["tokens_games"],
            "cost_usd": round(e["cost_usd"], 6) if e["cost_usd"] is not None else None,
            "cost_games": e["cost_games"],
        })
    rows.sort(key=lambda r: (
        r["win_rate"] is None,
        -(r["win_rate"] or 0),
        -(r["stone_diff_avg"] or 0),
        r["model_id"],
    ))
    return rows


def write_csv(path: str, rows: list[dict[str, Any]], columns: list[str]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in columns})
    replace_with_retry(tmp, path)


def write_results(games_root: str, results_root: str, tournament_id: str | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    games = load_games(games_root, tournament_id)
    matches = build_match_rows(games)
    ranking = build_ranking(games)
    write_csv(os.path.join(results_root, "matches.csv"), matches, MATCH_COLUMNS)
    write_csv(os.path.join(results_root, "ranking.csv"), ranking, RANKING_COLUMNS)
    return matches, ranking


def format_ranking(ranking: list[dict[str, Any]]) -> str:
    """端末表示用の成績表。"""
    headers = ["モデル", "局", "勝", "負", "分", "勝率", "先手勝率", "後手勝率", "石差平均",
               "反則負", "違法", "誤PASS", "形式", "平均秒", "技術エラー", "技術中断", "費用USD"]
    keys = ["model_id", "games", "wins", "losses", "draws", "win_rate", "win_rate_black",
            "win_rate_white", "stone_diff_avg", "foul_losses", "fouls_illegal", "fouls_wrong_pass",
            "fouls_format", "avg_response_sec", "tech_errors", "tech_aborts", "cost_usd"]
    table = [headers] + [["-" if r[k] is None else str(r[k]) for k in keys] for r in ranking]
    widths = [max(_width(row[i]) for row in table) for i in range(len(headers))]
    lines = []
    for row in table:
        lines.append("  ".join(cell + " " * (widths[i] - _width(cell)) for i, cell in enumerate(row)))
    return "\n".join(lines)


def _width(text: str) -> int:
    import unicodedata

    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)
