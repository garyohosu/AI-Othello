import csv
import json
import os

import pytest

import ai_runner
import game
import game_statistics as stats
import tournament as tour
from ai_runner import Attempt
from game import BLACK, WHITE

MOCK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_cli.py")


class ScriptedPlayer:
    """台本どおりに回答する高速なテスト用プレイヤー（プロセスを起動しない）。

    台本の要素:
      legal / last   合法手の先頭 / 末尾（なければ PASS）
      illegal        既に石があるマス
      pass / format  PASS / 説明付き回答
      tech           技術エラー（timeout）
      interrupt      KeyboardInterrupt を送出（Ctrl+C の再現）
    最後の要素は以後繰り返す。
    """

    def __init__(self, player_id, script=("legal",), elapsed=1.0, tech_elapsed=5.0):
        self.id = player_id
        self.script = list(script)
        self.calls = 0
        self.elapsed = elapsed
        self.tech_elapsed = tech_elapsed

    def cli_version(self):
        return "fake-1.0"

    def ask(self, board_text, color):
        action = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        board = game.parse_board(board_text)
        moves = game.legal_moves(board, color)
        prompt = ai_runner.build_prompt(board_text, color)
        if action == "interrupt":
            raise KeyboardInterrupt
        if action == "tech":
            return Attempt(prompt, "", "", None, self.tech_elapsed, None, ai_runner.TIMEOUT, "timeout")
        if action == "legal":
            answer = moves[0] if moves else "PASS"
        elif action == "last":
            answer = moves[-1] if moves else "PASS"
        elif action == "illegal":
            answer = next(game.index_to_coord(r, c) for r in range(8) for c in range(8)
                          if board[r][c] != game.EMPTY)
        elif action == "pass":
            answer = "PASS"
        elif action == "format":
            answer = "D3に打ちます"
        else:
            raise ValueError(action)
        return Attempt(prompt, answer + "\n", "", 0, self.elapsed, answer,
                       meta={"input_tokens": 100, "output_tokens": 1, "cost_usd": 0.01})


class NoSleep:
    def __init__(self):
        self.calls = []

    def __call__(self, sec):
        self.calls.append(sec)


def play(tmp_path, black, white, game_id="g1", rules=None, sleep=None):
    store = tour.GameStore(str(tmp_path), game_id)
    state = tour.play_game(store, {BLACK: black, WHITE: white}, rules or tour.Rules(), sleep=sleep or NoSleep())
    return store, state


def assert_consistent(store):
    """ログ再生・board.txt・state.json が一致していること。"""
    state = store.load_state()
    records = store.read_records()
    rep = tour.replay(records)
    with open(store.board_path, encoding="utf-8") as f:
        assert game.parse_board(f.read()) == rep["board"]
    assert game.board_sha256(rep["board"]) == state["board_sha256"]
    assert rep["fouls"] == state["fouls"]
    assert state["log_lines"] == len(records)


# ---------------------------------------------------------------- 判定


def test_judge_answer():
    legal = ["C4", "D3"]
    assert tour.judge_answer("D3", legal) == ("move", None)
    assert tour.judge_answer("A1", legal) == ("foul", "illegal_move")
    assert tour.judge_answer("PASS", legal) == ("foul", "wrong_pass")
    assert tour.judge_answer("PASS", []) == ("pass", None)
    assert tour.judge_answer("D3", []) == ("foul", "illegal_move")
    assert tour.judge_answer("d3", legal) == ("foul", "format")
    assert tour.judge_answer("", legal) == ("foul", "format")
    assert tour.judge_answer("I9", legal) == ("foul", "format")


def test_rules_backoff():
    rules = tour.Rules()
    assert [rules.backoff(n) for n in (1, 2, 3, 4, 5, 6, 7)] == [1, 2, 4, 8, 16, 30, 30]
    assert rules.backoff(1, retry_after=10) == 10
    assert rules.backoff(1, retry_after=100) == 30


# ---------------------------------------------------------------- 1局


def test_full_game_with_fake_players(tmp_path):
    store, state = play(tmp_path, ScriptedPlayer("a"), ScriptedPlayer("b", ["last"]))
    assert state["status"] == tour.FINISHED
    assert state["result"] == tour.RESULT_NORMAL
    stones = state["stones"]
    with open(store.board_path, encoding="utf-8") as f:
        board = game.parse_board(f.read())
    assert game.is_game_over(board)
    assert stones == {BLACK: game.count_stones(board)[BLACK], WHITE: game.count_stones(board)[WHITE]}
    assert state["fouls"] == {BLACK: 0, WHITE: 0}
    assert_consistent(store)
    rec = store.read_records()[0]
    assert rec["color"] == BLACK and rec["outcome"] == "move" and rec["model_id"] == "a"
    assert rec["prompt"].startswith(ai_runner.COMMON_INSTRUCTION)
    assert rec["cli_version"] == "fake-1.0"
    assert rec["board_after"] != rec["board_before"]


def test_fouls_below_limit_retry_same_turn_without_changing_board(tmp_path):
    black = ScriptedPlayer("a", ["illegal"] * 9 + ["legal"])
    store, state = play(tmp_path, black, ScriptedPlayer("b"))
    records = store.read_records()
    first_turn = records[:10]
    assert [r["outcome"] for r in first_turn] == ["foul"] * 9 + ["move"]
    assert [r["attempt"] for r in first_turn] == list(range(1, 11))
    assert {r["move_number"] for r in first_turn} == {1}
    assert {r["board_before"] for r in first_turn} == {game.format_board(game.initial_board())}
    assert all(r["board_after"] is None for r in first_turn[:9])
    assert [r["foul_count_after"] for r in first_turn[:9]] == list(range(1, 10))
    assert state["fouls"][BLACK] == 9
    assert state["result"] == tour.RESULT_NORMAL
    assert_consistent(store)


def test_tenth_foul_is_immediate_loss(tmp_path):
    store, state = play(tmp_path, ScriptedPlayer("a", ["illegal"]), ScriptedPlayer("b"))
    assert state["status"] == tour.FINISHED
    assert state["result"] == tour.RESULT_FOUL_LOSS
    assert state["winner"] == WHITE and state["loser"] == BLACK
    assert state["fouls"][BLACK] == 10
    records = store.read_records()
    assert len(records) == 10
    assert records[-1]["foul_count_after"] == 10
    assert state["stones"] == {BLACK: 2, WHITE: 2}
    assert_consistent(store)


def test_foul_count_is_not_reset_by_legal_move(tmp_path):
    black = ScriptedPlayer("a", ["illegal"] * 5 + ["legal"] + ["illegal"] * 5 + ["legal"])
    store, state = play(tmp_path, black, ScriptedPlayer("b"))
    assert state["result"] == tour.RESULT_FOUL_LOSS
    assert state["loser"] == BLACK
    assert state["fouls"][BLACK] == 10
    assert store.read_records()[-1]["move_number"] == 3  # 黒の2手目の手番で10回目
    assert_consistent(store)


def test_foul_limit_is_configurable(tmp_path):
    store, state = play(tmp_path, ScriptedPlayer("a", ["illegal"]), ScriptedPlayer("b"),
                        rules=tour.Rules(foul_limit=3))
    assert state["result"] == tour.RESULT_FOUL_LOSS
    assert len(store.read_records()) == 3


def test_foul_breakdown(tmp_path):
    black = ScriptedPlayer("a", ["illegal", "pass", "format", "illegal", "legal"])
    store, state = play(tmp_path, black, ScriptedPlayer("b"))
    assert state["foul_breakdown"][BLACK] == {"format": 1, "illegal_move": 2, "wrong_pass": 1}
    assert state["fouls"][BLACK] == 4


def test_white_fouls_counted_separately(tmp_path):
    white = ScriptedPlayer("b", ["illegal"] * 9 + ["legal"])
    black = ScriptedPlayer("a", ["illegal"] * 9 + ["legal"])
    store, state = play(tmp_path, black, white)
    assert state["fouls"] == {BLACK: 9, WHITE: 9}
    assert state["result"] == tour.RESULT_NORMAL


# ---------------------------------------------------------------- 技術エラー


def test_technical_errors_are_not_fouls_and_retry_with_backoff(tmp_path):
    sleep = NoSleep()
    black = ScriptedPlayer("a", ["tech", "tech", "tech", "legal"])
    store, state = play(tmp_path, black, ScriptedPlayer("b"), sleep=sleep)
    assert state["status"] == tour.FINISHED
    assert state["fouls"][BLACK] == 0
    assert state["tech_errors"][BLACK] == 3
    assert sleep.calls == [1, 2, 4]
    first = store.read_records()[:4]
    assert [r["outcome"] for r in first] == ["technical_error"] * 3 + ["move"]
    assert first[0]["error_type"] == ai_runner.TIMEOUT


def test_technical_abort_after_four_failures(tmp_path):
    sleep = NoSleep()
    store, state = play(tmp_path, ScriptedPlayer("a", ["tech"]), ScriptedPlayer("b"), sleep=sleep)
    assert state["status"] == tour.TECHNICAL_ABORT
    assert state["result"] == tour.RESULT_TECHNICAL_ABORT
    assert state["aborted_by"] == BLACK
    assert state["winner"] is None
    assert len(store.read_records()) == 4
    assert sleep.calls == [1, 2, 4]
    assert_consistent(store)


def test_technical_error_count_resets_each_turn(tmp_path):
    black = ScriptedPlayer("a", ["tech", "tech", "tech", "legal", "tech", "tech", "tech", "legal"])
    store, state = play(tmp_path, black, ScriptedPlayer("b"))
    assert state["status"] == tour.FINISHED
    assert state["tech_errors"][BLACK] == 6


def test_technical_errors_and_fouls_are_separate_counters(tmp_path):
    black = ScriptedPlayer("a", ["illegal", "tech", "illegal", "tech", "tech", "legal"])
    store, state = play(tmp_path, black, ScriptedPlayer("b"))
    assert state["status"] == tour.FINISHED
    assert state["fouls"][BLACK] == 2
    assert state["tech_errors"][BLACK] == 3


def test_fouls_do_not_reset_technical_error_count_within_turn(tmp_path):
    # 同じ手番内では反則を挟んでも技術エラー回数は累積し、4回目で技術中断
    black = ScriptedPlayer("a", ["tech", "illegal", "tech", "illegal", "tech", "tech", "legal"])
    store, state = play(tmp_path, black, ScriptedPlayer("b"))
    assert state["status"] == tour.TECHNICAL_ABORT
    assert state["fouls"][BLACK] == 2


# ---------------------------------------------------------------- 実プロセスのモックCLI


def mock_player(player_id, actions, **extra):
    data = {"id": player_id, "provider": "mock", "model": "m",
            "command": ["{python}", MOCK, "--actions", actions]}
    data.update(extra)
    return ai_runner.AIPlayer(ai_runner.ModelConfig.from_dict(data), default_timeout_sec=20)


def test_full_game_with_mock_cli_processes(tmp_path):
    black = mock_player("mock-text", "legal")
    white = mock_player("mock-json", "json", output="json", json_field="result",
                        usage_fields={"input_tokens": "usage.input_tokens",
                                      "output_tokens": "usage.output_tokens",
                                      "cost_usd": "total_cost_usd", "actual_model": "model"})
    store, state = play(tmp_path, black, white)
    assert state["status"] == tour.FINISHED
    assert state["result"] == tour.RESULT_NORMAL
    assert state["fouls"] == {BLACK: 0, WHITE: 0}
    assert_consistent(store)
    records = store.read_records()
    white_rec = next(r for r in records if r["color"] == WHITE)
    assert white_rec["actual_model"] == "mock-model-1"
    assert white_rec["input_tokens"] == 120
    black_rec = records[0]
    assert black_rec["input_tokens"] is None and black_rec["cost_usd"] is None
    # この組み合わせでは途中で合法手がなくなり、AIが正しく PASS を返す局面がある
    passes = [r for r in records if r["outcome"] == "pass"]
    assert passes and all(r["legal_moves"] == [] and r["extracted"] == "PASS" for r in passes)


def test_mock_cli_technical_abort(tmp_path):
    store, state = play(tmp_path, mock_player("bad", "exit"), mock_player("ok", "legal"))
    assert state["status"] == tour.TECHNICAL_ABORT
    records = store.read_records()
    assert [r["error_type"] for r in records] == [ai_runner.NONZERO_EXIT] * 4


def test_mock_cli_empty_answer_leads_to_foul_loss(tmp_path):
    store, state = play(tmp_path, mock_player("silent", "empty"), mock_player("ok", "legal"))
    assert state["result"] == tour.RESULT_FOUL_LOSS
    assert state["foul_breakdown"][BLACK]["format"] == 10


# ---------------------------------------------------------------- 停止・再開


def test_interrupt_and_resume_gives_same_result(tmp_path):
    _, reference = play(tmp_path / "ref", ScriptedPlayer("a"), ScriptedPlayer("b", ["last"]))

    black = ScriptedPlayer("a", ["legal"] * 10 + ["interrupt"])
    with pytest.raises(KeyboardInterrupt):
        play(tmp_path / "run", black, ScriptedPlayer("b", ["last"]))
    store = tour.GameStore(str(tmp_path / "run"), "g1")
    mid = store.load_state()
    assert mid["status"] == tour.IN_PROGRESS
    assert all(r["outcome"] == "move" for r in store.read_records())
    assert_consistent(store)

    _, resumed = play(tmp_path / "run", ScriptedPlayer("a"), ScriptedPlayer("b", ["last"]))
    assert resumed["stones"] == reference["stones"]
    assert resumed["move_number"] == reference["move_number"]
    assert_consistent(store)


def test_resume_keeps_foul_count(tmp_path):
    with pytest.raises(KeyboardInterrupt):
        play(tmp_path, ScriptedPlayer("a", ["illegal"] * 6 + ["interrupt"]), ScriptedPlayer("b"))
    _, state = play(tmp_path, ScriptedPlayer("a", ["illegal"]), ScriptedPlayer("b"))
    assert state["result"] == tour.RESULT_FOUL_LOSS
    store = tour.GameStore(str(tmp_path), "g1")
    assert len(store.read_records()) == 10


def test_resume_discards_uncommitted_log_and_fixes_board(tmp_path):
    with pytest.raises(KeyboardInterrupt):
        play(tmp_path, ScriptedPlayer("a", ["legal"] * 5 + ["interrupt"]), ScriptedPlayer("b"))
    store = tour.GameStore(str(tmp_path), "g1")
    committed = store.read_records()
    # moves.jsonl 追記と board.txt 更新の後、state.json 更新前に落ちた状態を再現
    fake = dict(committed[-1], seq=len(committed) + 1, extracted="A1")
    with open(store.log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(fake, ensure_ascii=False) + "\n")
        f.write('{"partial": ')  # 書きかけの行
    with open(store.board_path, "w", encoding="utf-8") as f:
        f.write(game.format_board(game.initial_board()))

    state, board = store.recover()
    assert store.read_records() == committed
    with open(store.log_path, encoding="utf-8") as f:
        assert len(f.read().splitlines()) == len(committed)
    with open(store.discarded_path, encoding="utf-8") as f:
        assert len(f.read().splitlines()) == 2
    with open(store.board_path, encoding="utf-8") as f:
        assert game.parse_board(f.read()) == board
    assert_consistent(store)

    _, final = play(tmp_path, ScriptedPlayer("a"), ScriptedPlayer("b"))
    assert final["status"] == tour.FINISHED


def test_resume_stops_on_tampered_log(tmp_path):
    with pytest.raises(KeyboardInterrupt):
        play(tmp_path, ScriptedPlayer("a", ["legal"] * 5 + ["interrupt"]), ScriptedPlayer("b"))
    store = tour.GameStore(str(tmp_path), "g1")
    with open(store.log_path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    rec = json.loads(lines[0])
    rec["extracted"] = "C4"  # D3 を C4 に書き換え
    lines[0] = json.dumps(rec, ensure_ascii=False)
    with open(store.log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with pytest.raises(tour.StateError):
        play(tmp_path, ScriptedPlayer("a"), ScriptedPlayer("b"))


def test_resume_stops_on_tampered_state(tmp_path):
    with pytest.raises(KeyboardInterrupt):
        play(tmp_path, ScriptedPlayer("a", ["illegal", "legal", "legal", "interrupt"]), ScriptedPlayer("b"))
    store = tour.GameStore(str(tmp_path), "g1")
    state = store.load_state()
    state["fouls"][BLACK] = 0
    with open(store.state_path, "w", encoding="utf-8") as f:
        json.dump(state, f)
    with pytest.raises(tour.StateError):
        play(tmp_path, ScriptedPlayer("a"), ScriptedPlayer("b"))


def test_resume_stops_when_log_shorter_than_state(tmp_path):
    with pytest.raises(KeyboardInterrupt):
        play(tmp_path, ScriptedPlayer("a", ["legal"] * 3 + ["interrupt"]), ScriptedPlayer("b"))
    store = tour.GameStore(str(tmp_path), "g1")
    with open(store.log_path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    with open(store.log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines[:-1]) + "\n")
    with pytest.raises(tour.StateError):
        store.recover()


def test_resume_rejects_different_players(tmp_path):
    with pytest.raises(KeyboardInterrupt):
        play(tmp_path, ScriptedPlayer("a", ["legal", "interrupt"]), ScriptedPlayer("b"))
    with pytest.raises(tour.StateError):
        play(tmp_path, ScriptedPlayer("x"), ScriptedPlayer("b"))


def test_finished_game_is_not_replayed(tmp_path):
    play(tmp_path, ScriptedPlayer("a"), ScriptedPlayer("b"))
    a, b = ScriptedPlayer("a"), ScriptedPlayer("b")
    play(tmp_path, a, b)
    assert a.calls == 0 and b.calls == 0


# ---------------------------------------------------------------- 総当たり


def test_schedule_round_robin_with_color_swap():
    games = tour.make_schedule(["a", "b", "c"], 2, "T")
    assert len(games) == 3 * 2 * 2
    pairs = [(g["black"], g["white"]) for g in games]
    for x, y in [("a", "b"), ("a", "c"), ("b", "c")]:
        assert pairs.count((x, y)) == 2
        assert pairs.count((y, x)) == 2
    assert all(g["black"] != g["white"] for g in games)
    assert len({g["game_id"] for g in games}) == len(games)
    with pytest.raises(ValueError):
        tour.make_schedule(["a", "a"], 1, "T")
    with pytest.raises(ValueError):
        tour.make_schedule(["a"], 1, "T")


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_tournament_csv(tmp_path):
    games_root, results_root = str(tmp_path / "games"), str(tmp_path / "results")
    players = {"a": ScriptedPlayer("a"), "b": ScriptedPlayer("b", ["last"]),
               "c": ScriptedPlayer("c", ["illegal"])}
    plan = tour.create_tournament(games_root, ["a", "b", "c"], 1, "T1")
    states = tour.run_tournament(games_root, plan, players, tour.Rules(), sleep=NoSleep())
    assert len(states) == 6
    matches, ranking = stats.write_results(games_root, results_root, "T1")

    rows = read_csv(os.path.join(results_root, "matches.csv"))
    assert len(rows) == 6
    assert {(r["black"], r["white"]) for r in rows} == {
        ("a", "b"), ("b", "a"), ("a", "c"), ("c", "a"), ("b", "c"), ("c", "b")}
    c_games = [r for r in rows if "c" in (r["black"], r["white"])]
    assert all(r["result_type"] == tour.RESULT_FOUL_LOSS and r["loser"] == "c" for r in c_games)

    rank = {r["model_id"]: r for r in read_csv(os.path.join(results_root, "ranking.csv"))}
    assert set(rank) == {"a", "b", "c"}
    for r in rank.values():
        assert int(r["games"]) == 4
        assert int(r["games_black"]) == 2 and int(r["games_white"]) == 2
    c = rank["c"]
    assert int(c["losses"]) == 4 and int(c["foul_losses"]) == 4
    assert float(c["win_rate"]) == 0.0
    assert int(c["fouls_illegal"]) == 40
    # 反則負けの対局は石差集計に含めない
    assert int(c["stone_diff_games"]) == 0 and c["stone_diff_avg"] == ""
    assert int(rank["a"]["stone_diff_games"]) == 2
    # 平均応答時間は回答が得られた試行のみ（ScriptedPlayer は 1.0 秒）
    assert float(rank["a"]["avg_response_sec"]) == 1.0
    assert ranking[-1]["model_id"] == "c"
    # トークン・費用は取得できた値を合計
    # c が黒の対局は a が1手も打たずに終わるため、取得できたのは3局
    assert int(rank["a"]["tokens_games"]) == 3
    assert float(rank["a"]["cost_usd"]) > 0


def test_win_rate_counts_draw_as_half_and_excludes_aborts():
    def st(gid, black, white, status, result, winner, stones=None, aborted_by=None):
        return ({
            "game_id": gid, "tournament_id": "T", "black": black, "white": white,
            "status": status, "result": result, "winner": winner,
            "loser": (WHITE if winner == BLACK else BLACK) if winner else None,
            "stones": stones, "move_number": 61, "fouls": {BLACK: 0, WHITE: 0},
            "foul_breakdown": {c: {"format": 0, "illegal_move": 0, "wrong_pass": 0} for c in (BLACK, WHITE)},
            "tech_errors": {BLACK: 0, WHITE: 0}, "aborted_by": aborted_by,
        }, [])

    games = [
        st("1", "a", "b", tour.FINISHED, tour.RESULT_NORMAL, None, {BLACK: 32, WHITE: 32}),
        st("2", "b", "a", tour.FINISHED, tour.RESULT_NORMAL, BLACK, {BLACK: 40, WHITE: 24}),
        st("3", "a", "b", tour.TECHNICAL_ABORT, tour.RESULT_TECHNICAL_ABORT, None, {BLACK: 10, WHITE: 8}, BLACK),
        st("4", "a", "b", tour.IN_PROGRESS, None, None),
    ]
    rank = {r["model_id"]: r for r in stats.build_ranking(games)}
    assert rank["a"]["games"] == 2
    assert rank["a"]["win_rate"] == 0.25
    assert rank["b"]["win_rate"] == 0.75
    assert rank["a"]["tech_aborts"] == 1 and rank["b"]["tech_aborts"] == 0
    assert rank["a"]["stone_diff_total"] == -16
    assert rank["b"]["win_rate_black"] == 1.0 and rank["b"]["win_rate_white"] == 0.5
    rows = stats.build_match_rows(games)
    assert [r["result_type"] for r in rows] == [tour.RESULT_NORMAL, tour.RESULT_NORMAL,
                                                tour.RESULT_TECHNICAL_ABORT, tour.IN_PROGRESS]
    assert rows[0]["winner"] == "draw"


def test_tournament_interrupt_and_resume(tmp_path):
    games_root = str(tmp_path / "games")
    plan = tour.create_tournament(games_root, ["a", "b", "c"], 1, "T2")
    flaky = ScriptedPlayer("c", ["legal"] * 40 + ["interrupt"])
    players = {"a": ScriptedPlayer("a"), "b": ScriptedPlayer("b", ["last"]), "c": flaky}
    with pytest.raises(KeyboardInterrupt):
        tour.run_tournament(games_root, plan, players, tour.Rules(), sleep=NoSleep())
    done_before = [g for g in plan["games"]
                   if tour.GameStore(games_root, g["game_id"]).exists()
                   and tour.GameStore(games_root, g["game_id"]).load_state()["status"] == tour.FINISHED]
    assert 0 < len(done_before) < 6

    plan = tour.load_tournament(games_root, "T2")
    players = {"a": ScriptedPlayer("a"), "b": ScriptedPlayer("b", ["last"]), "c": ScriptedPlayer("c")}
    states = tour.run_tournament(games_root, plan, players, tour.Rules(), sleep=NoSleep())
    assert len(states) == 6
    assert all(s["status"] == tour.FINISHED for s in states)
    for g in plan["games"]:
        assert_consistent(tour.GameStore(games_root, g["game_id"]))


def test_retry_aborted_creates_new_game_and_keeps_original(tmp_path):
    games_root, results_root = str(tmp_path / "games"), str(tmp_path / "results")
    plan = tour.create_tournament(games_root, ["a", "b"], 1, "T3")
    players = {"a": ScriptedPlayer("a", ["tech"]), "b": ScriptedPlayer("b")}
    states = tour.run_tournament(games_root, plan, players, tour.Rules(), sleep=NoSleep())
    assert all(s["status"] == tour.TECHNICAL_ABORT for s in states)

    plan = tour.load_tournament(games_root, "T3")
    added = tour.add_retries_for_aborted(games_root, plan)
    assert len(added) == 2 and all(a.endswith("-r1") for a in added)
    assert tour.add_retries_for_aborted(games_root, tour.load_tournament(games_root, "T3")) == []

    players = {"a": ScriptedPlayer("a"), "b": ScriptedPlayer("b")}
    plan = tour.load_tournament(games_root, "T3")
    states = tour.run_tournament(games_root, plan, players, tour.Rules(), sleep=NoSleep())
    assert [s["status"] for s in states] == [tour.TECHNICAL_ABORT] * 2 + [tour.FINISHED] * 2
    _, ranking = stats.write_results(games_root, results_root, "T3")
    rank = {r["model_id"]: r for r in ranking}
    assert rank["a"]["games"] == 2 and rank["a"]["tech_aborts"] == 2
    assert rank["b"]["tech_aborts"] == 0
    assert rank["a"]["tech_errors"] == 8


# ---------------------------------------------------------------- main.py


def test_main_cli_with_mock_models(tmp_path, capsys):
    import main

    # テストから実CLIを（--version も含めて）呼ばないよう、モックだけの設定を使う
    config = tmp_path / "models.yaml"
    config.write_text(
        "models:\n"
        "  - {id: mock-first, provider: mock, model: m,"
        " command: ['{python}', '{project}/tests/mock_cli.py', '--actions', 'legal']}\n"
        "  - {id: mock-json, provider: mock, model: m, output: json, json_field: result,"
        " command: ['{python}', '{project}/tests/mock_cli.py', '--actions', 'json']}\n"
        "  - {id: missing-off, provider: cli, model: m, command: ['no-such-cli-ai-othello'], enabled: false}\n",
        encoding="utf-8",
    )
    config = str(config)
    rules = os.path.join(ai_runner.PROJECT_ROOT, "config", "rules.yaml")
    base = ["--config", config, "--rules", rules,
            "--games-dir", str(tmp_path / "games"), "--results-dir", str(tmp_path / "results")]

    # 無効なモデルのCLIが見つからなくても validate は失敗しない
    assert main.main(base + ["validate"]) == 0
    assert "SKIP missing-off" in capsys.readouterr().out
    assert main.main(base + ["list-models"]) == 0
    assert main.main(base + ["tournament", "--models", "mock-first,mock-json"]) == 0
    out = capsys.readouterr().out
    assert "大会ID:" in out and "全2局" in out
    rows = read_csv(str(tmp_path / "results" / "matches.csv"))
    assert len(rows) == 2
    assert {(r["black"], r["white"]) for r in rows} == {("mock-first", "mock-json"), ("mock-json", "mock-first")}
    assert main.main(base + ["results"]) == 0
    assert main.main(base + ["play", "--black", "mock-first", "--white", "nope"]) == 2


def test_main_refuses_real_cli_without_confirmation(tmp_path, capsys, monkeypatch):
    import main

    cfg = tmp_path / "models.yaml"
    cfg.write_text(
        "models:\n"
        "  - {id: real-a, provider: cli, model: m, command: ['no-such-cli'], sandbox: restricted}\n"
        "  - {id: real-b, provider: cli, model: m, command: ['no-such-cli']}\n",
        encoding="utf-8",
    )
    base = ["--config", str(cfg), "--games-dir", str(tmp_path / "games"), "--results-dir", str(tmp_path / "r")]
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    # sandbox 未確認のモデルは大会に参加できない
    assert main.main(base + ["tournament"]) == 2
    assert "サンドボックス" in capsys.readouterr().out
    # play でも --allow-unrestricted がなければ拒否
    assert main.main(base + ["play", "--black", "real-a", "--white", "real-b"]) == 2
    # 非対話環境で --yes がなければ実行しない
    assert main.main(base + ["play", "--black", "real-a", "--white", "real-b", "--allow-unrestricted"]) == 2
    assert "--yes" in capsys.readouterr().out
    # 運用ログ（_logs）以外の対局データは作られていない
    assert set(os.listdir(tmp_path / "games")) <= {"_logs"}


# ---------------------------------------------------------------- ファイル置換のリトライ


def test_replace_retry_logs_and_succeeds(tmp_path, monkeypatch, caplog):
    src, dst = tmp_path / "a.tmp", tmp_path / "a.json"
    src.write_text("new", encoding="utf-8")
    dst.write_text("old", encoding="utf-8")
    real_replace = os.replace
    calls = []

    def flaky(s, d):
        calls.append(1)
        if len(calls) <= 2:
            exc = PermissionError(13, "Access is denied")
            raise exc
        return real_replace(s, d)

    monkeypatch.setattr(tour.os, "replace", flaky)
    sleeps = []
    with caplog.at_level("WARNING", logger="ai_othello.fs"):
        tour.replace_with_retry(str(src), str(dst), sleep=sleeps.append)
    assert dst.read_text(encoding="utf-8") == "new"
    assert sleeps == [0.05, 0.1]
    messages = [r.getMessage() for r in caplog.records]
    assert len(messages) == 3
    assert "attempt=1/10" in messages[0] and "a.json" in messages[0] and "PermissionError" in messages[0]
    assert "succeeded after retry" in messages[2] and "attempt=3/10" in messages[2]


def test_replace_retry_gives_up_and_keeps_old_file(tmp_path, monkeypatch, caplog):
    src, dst = tmp_path / "a.tmp", tmp_path / "a.json"
    src.write_text("new", encoding="utf-8")
    dst.write_text("old", encoding="utf-8")

    def always_fail(s, d):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(tour.os, "replace", always_fail)
    sleeps = []
    with caplog.at_level("WARNING", logger="ai_othello.fs"):
        with pytest.raises(PermissionError):
            tour.replace_with_retry(str(src), str(dst), sleep=sleeps.append)
    assert len(sleeps) == 9
    assert abs(sum(sleeps) - 2.25) < 1e-9
    assert dst.read_text(encoding="utf-8") == "old"
    assert caplog.records[-1].levelname == "ERROR" and "attempt=10/10" in caplog.records[-1].getMessage()


def test_replace_retry_does_not_retry_other_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        tour.replace_with_retry(str(tmp_path / "missing"), str(tmp_path / "x"), sleep=lambda s: None)


def test_failed_state_replace_keeps_commit_point_consistent(tmp_path, monkeypatch):
    with pytest.raises(KeyboardInterrupt):
        play(tmp_path, ScriptedPlayer("a", ["legal"] * 3 + ["interrupt"]), ScriptedPlayer("b"))
    store = tour.GameStore(str(tmp_path), "g1")
    committed = store.read_records()
    real_replace = os.replace

    def fail_state(s, d):
        if d.endswith("state.json"):
            raise PermissionError(13, "Access is denied")
        return real_replace(s, d)

    monkeypatch.setattr(tour.os, "replace", fail_state)
    monkeypatch.setattr(tour.time, "sleep", lambda s: None)
    with pytest.raises(PermissionError):
        play(tmp_path, ScriptedPlayer("a"), ScriptedPlayer("b"))
    monkeypatch.setattr(tour.os, "replace", real_replace)
    # state.json は更新されていないので、追記済みのログ1行は未確定として切り捨てられる
    state, board = store.recover()
    assert store.read_records() == committed
    assert_consistent(store)
    _, final = play(tmp_path, ScriptedPlayer("a"), ScriptedPlayer("b"))
    assert final["status"] == tour.FINISHED


def test_records_prompt_via(tmp_path):
    store, _ = play(tmp_path, ScriptedPlayer("a"), ScriptedPlayer("b"))
    assert store.read_records()[0]["prompt_via"] == "stdin"


def test_main_writes_operation_log(tmp_path):
    import logging

    import main

    main.setup_logging(str(tmp_path / "games"))
    logging.getLogger("ai_othello.fs").warning("replace retry: test-entry")
    for h in logging.getLogger("ai_othello").handlers:
        h.flush()
    log = (tmp_path / "games" / "_logs" / "ai-othello.log").read_text(encoding="utf-8")
    assert "replace retry: test-entry" in log
    main.setup_logging(str(tmp_path / "other"))  # ハンドラを付け替えてファイルを閉じる
