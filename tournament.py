"""対局の進行、反則・技術エラー管理、保存と再開、総当たり大会。

保存は「moves.jsonl 追記 → board.txt 置換 → state.json 置換」の順で行い、
state.json の置換完了をコミット点とする。再開時は state.json の log_lines を
超えるログ行を未確定として切り捨て、ログを再生して整合性を確かめる。
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Iterable, Protocol

import ai_runner
import game
from game import BLACK, WHITE

IN_PROGRESS = "in_progress"
FINISHED = "finished"
TECHNICAL_ABORT = "technical_abort"

RESULT_NORMAL = "normal"
RESULT_FOUL_LOSS = "foul_loss"
RESULT_TECHNICAL_ABORT = "technical_abort"

FOUL_TYPES = ("format", "illegal_move", "wrong_pass")

fs_log = logging.getLogger("ai_othello.fs")


class StateError(RuntimeError):
    """保存データの不整合。自動修復できないので処理を止める。"""


@dataclass
class Rules:
    foul_limit: int = 10
    technical_retry_limit: int = 3
    default_timeout_sec: float = 120.0
    backoff_base_sec: float = 1.0
    backoff_max_sec: float = 30.0
    games_per_side: int = 1

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Rules":
        data = data or {}
        rules = cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})
        if rules.foul_limit < 1 or rules.technical_retry_limit < 0 or rules.games_per_side < 1:
            raise ValueError("rules.yaml の値が不正")
        return rules

    def backoff(self, error_count: int, retry_after: float | None = None) -> float:
        """技術エラー後の待機秒数。1→2→4…（上限 backoff_max_sec）。"""
        if retry_after is not None and retry_after >= 0:
            return min(retry_after, self.backoff_max_sec)
        return min(self.backoff_base_sec * 2 ** (error_count - 1), self.backoff_max_sec)


class Player(Protocol):
    id: str

    def ask(self, board_text: str, color: str) -> ai_runner.Attempt: ...

    def cli_version(self) -> str | None: ...


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


REPLACE_ATTEMPTS = 10
REPLACE_WAIT_SEC = 0.05


def replace_with_retry(
    src: str,
    dst: str,
    attempts: int = REPLACE_ATTEMPTS,
    wait_sec: float = REPLACE_WAIT_SEC,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """os.replace を PermissionError のときだけリトライする。

    Windows ではウイルス対策ソフトや検索インデクサが一瞬ファイルを開いていると
    PermissionError になることがある（原因は未確定。Result00001/00002 参照）。
    待機は 0.05, 0.10, …, 0.45 秒で、既定の10回なら合計 約2.25秒。
    置換に失敗しても置換先は元の内容のまま残るので、コミット点（state.json）の
    整合性は保たれる。リトライのたびに、ファイル名・操作・例外・試行回数を
    ログに記録する（内容は書かない）。
    """
    for i in range(1, attempts + 1):
        try:
            os.replace(src, dst)
            if i > 1:
                fs_log.warning("replace succeeded after retry: dst=%s attempt=%d/%d", dst, i, attempts)
            return
        except PermissionError as exc:
            detail = (
                f"op=replace src={src} dst={dst} attempt={i}/{attempts} "
                f"exc={type(exc).__name__} errno={exc.errno} winerror={getattr(exc, 'winerror', None)}"
            )
            if i == attempts:
                fs_log.error("replace failed, giving up: %s", detail)
                raise
            fs_log.warning("replace retry: %s", detail)
            sleep(wait_sec * i)


def _atomic_write(path: str, text: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    replace_with_retry(tmp, path)


def _empty_fouls() -> dict[str, dict[str, int]]:
    return {c: {t: 0 for t in FOUL_TYPES} for c in (BLACK, WHITE)}


def replay(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """確定済みログを初期盤面から再生し、盤面と手番状態を復元する。"""
    board = game.initial_board()
    turn = BLACK
    move_number = 1
    fouls = {BLACK: 0, WHITE: 0}
    breakdown = _empty_fouls()
    turn_tech_errors = 0
    turn_attempts = 0
    for i, rec in enumerate(records, start=1):
        if rec.get("seq") != i:
            raise StateError(f"ログの seq が連番でない: {i}行目")
        if rec.get("color") != turn:
            raise StateError(f"ログの手番が一致しない: seq={i}")
        outcome = rec.get("outcome")
        turn_attempts += 1
        if outcome == "move":
            try:
                board = game.apply_move(board, turn, rec["extracted"])
            except (game.IllegalMoveError, ValueError, KeyError) as exc:
                raise StateError(f"ログの着手を再生できない: seq={i}: {exc}") from exc
            turn, move_number, turn_tech_errors, turn_attempts = game.opponent(turn), move_number + 1, 0, 0
        elif outcome == "pass":
            if game.has_legal_move(board, turn):
                raise StateError(f"合法手があるのに pass として記録されている: seq={i}")
            turn, move_number, turn_tech_errors, turn_attempts = game.opponent(turn), move_number + 1, 0, 0
        elif outcome == "foul":
            ftype = rec.get("foul_type")
            if ftype not in FOUL_TYPES:
                raise StateError(f"未知の反則種別: seq={i}")
            fouls[turn] += 1
            breakdown[turn][ftype] += 1
        elif outcome == "technical_error":
            turn_tech_errors += 1
        else:
            raise StateError(f"未知の outcome: seq={i}: {outcome!r}")
    return {
        "board": board,
        "turn": turn,
        "move_number": move_number,
        "fouls": fouls,
        "foul_breakdown": breakdown,
        "turn_tech_errors": turn_tech_errors,
        "turn_attempts": turn_attempts,
    }


class GameStore:
    """games/<game_id>/ 配下の board.txt・state.json・moves.jsonl を扱う。"""

    def __init__(self, games_root: str, game_id: str):
        self.game_id = game_id
        self.dir = os.path.join(games_root, game_id)
        self.board_path = os.path.join(self.dir, "board.txt")
        self.state_path = os.path.join(self.dir, "state.json")
        self.log_path = os.path.join(self.dir, "moves.jsonl")
        self.discarded_path = os.path.join(self.dir, "moves.discarded.jsonl")
        self.work_dir = os.path.join(self.dir, "workdir")

    def exists(self) -> bool:
        return os.path.exists(self.state_path)

    def create(self, black: str, white: str, tournament_id: str | None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        if os.path.exists(self.log_path) and os.path.getsize(self.log_path) > 0 and not self.exists():
            raise StateError(f"{self.dir}: state.json がないのにログがある")
        os.makedirs(self.work_dir, exist_ok=True)
        board = game.initial_board()
        state: dict[str, Any] = {
            "game_id": self.game_id,
            "tournament_id": tournament_id,
            "black": black,
            "white": white,
            "turn": BLACK,
            "move_number": 1,
            "status": IN_PROGRESS,
            "result": None,
            "winner": None,
            "loser": None,
            "stones": None,
            "fouls": {BLACK: 0, WHITE: 0},
            "foul_breakdown": _empty_fouls(),
            "tech_errors": {BLACK: 0, WHITE: 0},
            "turn_tech_errors": 0,
            "turn_attempts": 0,
            "aborted_by": None,
            "board_sha256": game.board_sha256(board),
            "log_lines": 0,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "finished_at": None,
        }
        if extra:
            state.update(extra)
        with open(self.log_path, "w", encoding="utf-8"):
            pass
        _atomic_write(self.board_path, game.format_board(board))
        _atomic_write(self.state_path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        return state

    def load_state(self) -> dict[str, Any]:
        try:
            with open(self.state_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise StateError(f"{self.state_path} を読めない: {exc}") from exc

    def read_records(self) -> list[dict[str, Any]]:
        """確定済み（state.json の log_lines まで）のログを返す。"""
        state = self.load_state()
        lines, _ = self._read_lines()
        return [json.loads(line) for line in lines[: state["log_lines"]]]

    def _read_lines(self) -> tuple[list[str], bool]:
        """ログの行一覧と、最終行が改行で終わっているか（書き込み途中でないか）を返す。"""
        if not os.path.exists(self.log_path):
            return [], True
        with open(self.log_path, encoding="utf-8", newline="") as f:
            text = f.read()
        complete = text.endswith("\n") or text == ""
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        return lines, complete

    def recover(self) -> tuple[dict[str, Any], game.Board]:
        """未確定のログを切り捨て、ログ・盤面・状態の整合性を確認する。

        state.json 更新前に中断した場合の差分だけを修復し、それ以外の
        不一致は StateError で止める。
        """
        state = self.load_state()
        lines, _ = self._read_lines()
        committed = state["log_lines"]
        if len(lines) < committed:
            raise StateError(f"{self.game_id}: ログが state.json より短い ({len(lines)} < {committed})")
        if len(lines) > committed:
            extra = lines[committed:]
            with open(self.discarded_path, "a", encoding="utf-8", newline="\n") as f:
                for line in extra:
                    f.write(line + "\n")
            _atomic_write(self.log_path, "".join(line + "\n" for line in lines[:committed]))
        try:
            records = [json.loads(line) for line in lines[:committed]]
        except json.JSONDecodeError as exc:
            raise StateError(f"{self.game_id}: 確定済みログが壊れている: {exc}") from exc
        rep = replay(records)
        board = rep["board"]
        if game.board_sha256(board) != state["board_sha256"]:
            raise StateError(f"{self.game_id}: ログを再生した盤面と state.json のハッシュが一致しない")
        for key in ("turn", "move_number", "fouls", "foul_breakdown", "turn_tech_errors", "turn_attempts"):
            if rep[key] != state.get(key):
                raise StateError(f"{self.game_id}: state.json の {key} がログと一致しない")
        file_board: game.Board | None
        try:
            with open(self.board_path, encoding="utf-8", newline="") as f:
                file_board = game.parse_board(f.read())
        except (OSError, game.BoardFormatError):
            file_board = None
        if file_board != board:
            _atomic_write(self.board_path, game.format_board(board))
        os.makedirs(self.work_dir, exist_ok=True)
        return state, board

    def commit(self, record: dict[str, Any] | None, board: game.Board, state: dict[str, Any]) -> None:
        if record is not None:
            record["seq"] = state["log_lines"] + 1
            line = json.dumps(record, ensure_ascii=False) + "\n"
            with open(self.log_path, "a", encoding="utf-8", newline="\n") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
            state["log_lines"] += 1
        _atomic_write(self.board_path, game.format_board(board))
        state["board_sha256"] = game.board_sha256(board)
        state["updated_at"] = now_iso()
        _atomic_write(self.state_path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def _sandbox_note(player: Any) -> str | None:
    cfg = getattr(player, "cfg", None)
    if cfg is None or cfg.sandbox == "restricted":
        return None
    note = f"sandbox={cfg.sandbox}: 任意コード実行・ファイル編集を制限できていない可能性がある"
    if cfg.sandbox_note:
        note += f" ({cfg.sandbox_note})"
    return note


def _finish_normal(state: dict[str, Any], board: game.Board) -> None:
    counts = game.count_stones(board)
    w = game.winner(board)
    state.update(
        status=FINISHED,
        result=RESULT_NORMAL,
        winner=w,
        loser=game.opponent(w) if w else None,
        stones={BLACK: counts[BLACK], WHITE: counts[WHITE]},
        finished_at=now_iso(),
    )


def judge_answer(answer: str, legal: list[str]) -> tuple[str, str | None]:
    """回答本文を判定し (outcome, foul_type) を返す。

    outcome は move / pass / foul。foul_type は format / illegal_move / wrong_pass。
    """
    kind = ai_runner.classify_answer(answer)
    if kind == "format":
        return "foul", "format"
    if kind == "pass":
        return ("foul", "wrong_pass") if legal else ("pass", None)
    return ("move", None) if answer in legal else ("foul", "illegal_move")


def play_game(
    store: GameStore,
    players: dict[str, Player],
    rules: Rules,
    tournament_id: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
    on_event: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """1局を最後まで進める（既存の対局なら続きから再開する）。"""
    log = on_event or (lambda msg: None)
    if store.exists():
        state, board = store.recover()
        if state["black"] != players[BLACK].id or state["white"] != players[WHITE].id:
            raise StateError(f"{store.game_id}: 再開時のプレイヤーが一致しない")
    else:
        state = store.create(players[BLACK].id, players[WHITE].id, tournament_id)
        board = game.initial_board()
    if state["status"] != IN_PROGRESS:
        return state

    while True:
        if game.is_game_over(board):
            _finish_normal(state, board)
            store.commit(None, board, state)
            log(f"{store.game_id}: 終局 {state['stones']}")
            return state

        color = state["turn"]
        player = players[color]
        legal = game.legal_moves(board, color)
        board_text = game.format_board(board)
        attempt = player.ask(board_text, color)  # Ctrl+C はここで送出され、この試行は記録しない
        state["turn_attempts"] += 1
        record: dict[str, Any] = {
            "game_id": store.game_id,
            "move_number": state["move_number"],
            "color": color,
            "model_id": player.id,
            "attempt": state["turn_attempts"],
            "board_before": board_text,
            "legal_moves": legal,  # 分析用。AIには渡していない
            "prompt": attempt.prompt,
            "board_delivery": attempt.board_delivery,
            "prompt_via": attempt.prompt_via,
            "raw_stdout": attempt.raw_stdout,
            "raw_stderr": attempt.raw_stderr,
            "exit_code": attempt.exit_code,
            "extracted": attempt.answer,
            "outcome": None,
            "foul_type": None,
            "error_type": attempt.error_type,
            "error_detail": attempt.error_detail,
            "foul_count_after": state["fouls"][color],
            "board_after": None,
            "elapsed_sec": round(attempt.elapsed_sec, 3),
            "actual_model": attempt.meta.get("actual_model"),
            "cli_version": player.cli_version(),
            "input_tokens": attempt.meta.get("input_tokens"),
            "output_tokens": attempt.meta.get("output_tokens"),
            "cost_usd": attempt.meta.get("cost_usd"),
            "sandbox_note": _sandbox_note(player),
            "timestamp": now_iso(),
        }

        if attempt.error_type:
            state["turn_tech_errors"] += 1
            state["tech_errors"][color] += 1
            record["outcome"] = "technical_error"
            aborted = state["turn_tech_errors"] > rules.technical_retry_limit
            if aborted:
                state.update(
                    status=TECHNICAL_ABORT,
                    result=RESULT_TECHNICAL_ABORT,
                    aborted_by=color,
                    stones={BLACK: game.count_stones(board)[BLACK], WHITE: game.count_stones(board)[WHITE]},
                    finished_at=now_iso(),
                )
            store.commit(record, board, state)
            log(f"{store.game_id}: {player.id} 技術エラー {attempt.error_type} ({state['turn_tech_errors']}回目)")
            if aborted:
                log(f"{store.game_id}: 技術中断")
                return state
            sleep(rules.backoff(state["turn_tech_errors"], attempt.retry_after_sec))
            continue

        answer = attempt.answer or ""
        outcome, foul = judge_answer(answer, legal)
        record["outcome"] = outcome

        if foul:
            state["fouls"][color] += 1
            state["foul_breakdown"][color][foul] += 1
            record.update(outcome="foul", foul_type=foul, foul_count_after=state["fouls"][color])
            log(f"{store.game_id}: {player.id} 反則 {foul} {answer!r} (累積{state['fouls'][color]}回)")
            if state["fouls"][color] >= rules.foul_limit:
                counts = game.count_stones(board)
                state.update(
                    status=FINISHED,
                    result=RESULT_FOUL_LOSS,
                    winner=game.opponent(color),
                    loser=color,
                    stones={BLACK: counts[BLACK], WHITE: counts[WHITE]},
                    finished_at=now_iso(),
                )
                store.commit(record, board, state)
                log(f"{store.game_id}: {player.id} 反則負け")
                return state
            store.commit(record, board, state)
            continue

        if record["outcome"] == "move":
            board = game.apply_move(board, color, answer)
            record["board_after"] = game.format_board(board)
        state["turn"] = game.opponent(color)
        state["move_number"] += 1
        state["turn_tech_errors"] = 0
        state["turn_attempts"] = 0
        store.commit(record, board, state)
        log(f"{store.game_id}: {player.id} {answer}")


# ---------------------------------------------------------------- 総当たり


def tournaments_dir(games_root: str) -> str:
    return os.path.join(games_root, "_tournaments")


def plan_path(games_root: str, tournament_id: str) -> str:
    return os.path.join(tournaments_dir(games_root), f"{tournament_id}.json")


def make_schedule(model_ids: list[str], games_per_side: int, tournament_id: str) -> list[dict[str, Any]]:
    """自己対戦を除く全組み合わせについて、黒白を入れ替えて games_per_side 局ずつ組む。"""
    if len(set(model_ids)) != len(model_ids):
        raise ValueError("モデルIDが重複している")
    if len(model_ids) < 2:
        raise ValueError("総当たりには2モデル以上が必要")
    games: list[dict[str, Any]] = []
    n = 0
    for i, a in enumerate(model_ids):
        for b in model_ids[i + 1:]:
            for k in range(games_per_side):
                for black, white in ((a, b), (b, a)):
                    n += 1
                    games.append({
                        "game_id": f"{tournament_id}-{black}-vs-{white}-{n:03d}",
                        "black": black,
                        "white": white,
                        "retry_of": None,
                    })
    return games


def create_tournament(games_root: str, model_ids: list[str], games_per_side: int, tournament_id: str | None = None) -> dict[str, Any]:
    tournament_id = tournament_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    path = plan_path(games_root, tournament_id)
    if os.path.exists(path):
        raise StateError(f"大会 {tournament_id} は既にある")
    plan = {
        "tournament_id": tournament_id,
        "created_at": now_iso(),
        "models": model_ids,
        "games_per_side": games_per_side,
        "games": make_schedule(model_ids, games_per_side, tournament_id),
    }
    os.makedirs(tournaments_dir(games_root), exist_ok=True)
    _atomic_write(path, json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    return plan


def load_tournament(games_root: str, tournament_id: str) -> dict[str, Any]:
    path = plan_path(games_root, tournament_id)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"大会ファイルを読めない: {path}: {exc}") from exc


def add_retries_for_aborted(games_root: str, plan: dict[str, Any]) -> list[str]:
    """技術中断した対局を、別の対局IDで再対局する予定として追加する。元のログは残す。"""
    retried = {g["retry_of"] for g in plan["games"] if g.get("retry_of")}
    added: list[str] = []
    for g in list(plan["games"]):
        store = GameStore(games_root, g["game_id"])
        if g["game_id"] in retried or not store.exists():
            continue
        if store.load_state()["status"] != TECHNICAL_ABORT:
            continue
        base = g["game_id"]
        k = 1
        existing = {x["game_id"] for x in plan["games"]}
        while f"{base}-r{k}" in existing:
            k += 1
        new_id = f"{base}-r{k}"
        plan["games"].append({"game_id": new_id, "black": g["black"], "white": g["white"], "retry_of": base})
        added.append(new_id)
    if added:
        _atomic_write(plan_path(games_root, plan["tournament_id"]), json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    return added


def run_tournament(
    games_root: str,
    plan: dict[str, Any],
    players: dict[str, Player],
    rules: Rules,
    sleep: Callable[[float], None] = time.sleep,
    on_event: Callable[[str], None] | None = None,
    before_game: Callable[[GameStore, dict[str, Player]], None] | None = None,
    after_game: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """予定順に対局を直列実行する。完了・技術中断済みの対局は飛ばす。"""
    states = []
    for g in plan["games"]:
        store = GameStore(games_root, g["game_id"])
        if store.exists():
            state = store.load_state()
            if state["status"] != IN_PROGRESS:
                states.append(state)
                continue
        pair = {BLACK: players[g["black"]], WHITE: players[g["white"]]}
        if before_game:
            before_game(store, pair)
        state = play_game(
            store,
            pair,
            rules,
            tournament_id=plan["tournament_id"],
            sleep=sleep,
            on_event=on_event,
        )
        states.append(state)
        if after_game:
            after_game(state)
    return states
