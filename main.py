"""AI-Othello のコマンドライン入口。

  play         1局だけ対局する
  tournament   総当たり大会を実行・再開する
  results      成績を集計・表示する
  list-models  設定済みモデルの一覧
  validate     設定とCLIの存在を確認する（--live で1手だけ疎通確認）
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from typing import Any

import yaml

import ai_runner
import game
import game_statistics as stats
import tournament as tour
from game import BLACK, WHITE

EXIT_OK = 0
EXIT_RUNTIME = 1
EXIT_CONFIG = 2
EXIT_INTERRUPTED = 130


def _load_yaml(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config(args: argparse.Namespace) -> tuple[list[ai_runner.ModelConfig], tour.Rules]:
    if not os.path.exists(args.config):
        raise ai_runner.ConfigError(
            f"{args.config} がない。config/models.example.yaml をコピーして作成する"
        )
    models = ai_runner.load_models(_load_yaml(args.config))
    rules = tour.Rules.from_dict(_load_yaml(args.rules) if os.path.exists(args.rules) else {})
    return models, rules


def _select(models: list[ai_runner.ModelConfig], ids: list[str]) -> list[ai_runner.ModelConfig]:
    by_id = {m.id: m for m in models}
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        raise ai_runner.ConfigError(f"未登録のモデル: {', '.join(unknown)}")
    return [by_id[i] for i in ids]


def _confirm_real_cli(models: list[ai_runner.ModelConfig], games: int, rules: tour.Rules, assume_yes: bool) -> bool:
    """実CLI（課金の可能性あり）を使う前に、対象と呼び出し回数の目安を示して確認する。"""
    real = [m for m in models if not m.is_mock]
    if not real:
        return True
    print("実際のAI CLIを呼び出します（課金が発生する可能性があります）。")
    for m in real:
        print(f"  - {m.id}: provider={m.provider} model={m.model} sandbox={m.sandbox}")
    print(f"  対局数: {games}")
    print("  呼び出し回数の目安: 1局あたり通常60～70回。反則（各プレイヤー最大"
          f"{rules.foul_limit - 1}回の再試行）と技術エラー（1手番あたり最大"
          f"{rules.technical_retry_limit}回のリトライ）で増える。")
    print("  費用はCLIが返す実績値のみ記録する。費用上限は保証しない。")
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print("非対話環境では --yes が必要です。中止しました。")
        return False
    return input("実行するには yes と入力: ").strip() == "yes"


def _players(models: list[ai_runner.ModelConfig], rules: tour.Rules) -> dict[str, ai_runner.AIPlayer]:
    return {m.id: ai_runner.AIPlayer(m, rules.default_timeout_sec) for m in models}


def _bind_workdir(store: tour.GameStore, players: dict[str, Any]) -> None:
    """AI CLI は対局ごとの空の作業ディレクトリで実行する。"""
    os.makedirs(store.work_dir, exist_ok=True)
    for p in players.values():
        if isinstance(p, ai_runner.AIPlayer):
            p.cwd = os.path.abspath(store.work_dir)


def _print_event(msg: str) -> None:
    print(msg, flush=True)


def cmd_play(args: argparse.Namespace) -> int:
    models, rules = load_config(args)
    if args.resume:
        store = tour.GameStore(args.games_dir, args.resume)
        if not store.exists():
            print(f"対局 {args.resume} がない")
            return EXIT_CONFIG
        state = store.load_state()
        black_id, white_id = state["black"], state["white"]
    else:
        if not (args.black and args.white):
            print("--black と --white を指定する（再開は --resume）")
            return EXIT_CONFIG
        black_id, white_id = args.black, args.white
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        n = 1
        while os.path.exists(os.path.join(args.games_dir, f"{stamp}-{black_id}-vs-{white_id}-{n:03d}")):
            n += 1
        store = tour.GameStore(args.games_dir, f"{stamp}-{black_id}-vs-{white_id}-{n:03d}")
    selected = _select(models, [black_id, white_id])
    unrestricted = [m.id for m in selected if not m.is_mock and m.sandbox != "restricted"]
    if unrestricted and not args.allow_unrestricted:
        print(f"サンドボックス制限を確認できていないモデル: {', '.join(unrestricted)}")
        print("検証目的で動かす場合のみ --allow-unrestricted を付ける（実大会では使えない）")
        return EXIT_CONFIG
    if not _confirm_real_cli(selected, 1, rules, args.yes):
        return EXIT_CONFIG
    by_id = _players(selected, rules)
    players = {BLACK: by_id[black_id], WHITE: by_id[white_id]}
    _bind_workdir(store, players)
    print(f"対局ID: {store.game_id}")
    state = tour.play_game(store, players, rules, on_event=_print_event)
    _print_game_summary(state)
    return EXIT_OK


def _print_game_summary(state: dict[str, Any]) -> None:
    result = state["result"]
    if result == tour.RESULT_TECHNICAL_ABORT:
        print(f"技術中断（{state[state['aborted_by']]}）。通常の勝敗から除外する。")
        return
    stones = state["stones"]
    winner = state["winner"]
    head = "反則負け" if result == tour.RESULT_FOUL_LOSS else "終局"
    text = f"{state[winner]} の勝ち" if winner else "引き分け"
    print(f"{head}: 黒 {stones[BLACK]} - 白 {stones[WHITE]}、{text}")


def cmd_tournament(args: argparse.Namespace) -> int:
    models, rules = load_config(args)
    if args.resume:
        plan = tour.load_tournament(args.games_dir, args.resume)
        selected = _select(models, plan["models"])
        if args.retry_aborted:
            added = tour.add_retries_for_aborted(args.games_dir, plan)
            print(f"技術中断の再対局を追加: {len(added)}局")
    else:
        if args.retry_aborted:
            print("--retry-aborted は --resume と一緒に使う")
            return EXIT_CONFIG
        ids = args.models.split(",") if args.models else [m.id for m in models if m.enabled]
        selected = _select(models, ids)
        games_per_side = args.games_per_side or rules.games_per_side
        plan = None
    unrestricted = [m.id for m in selected if not m.is_mock and m.sandbox != "restricted"]
    if unrestricted:
        print(f"サンドボックス制限を確認できていないモデルは大会に参加できない: {', '.join(unrestricted)}")
        return EXIT_CONFIG
    if plan is None:
        plan = tour.create_tournament(args.games_dir, [m.id for m in selected], games_per_side)
    remaining = sum(
        1 for g in plan["games"]
        if not tour.GameStore(args.games_dir, g["game_id"]).exists()
        or tour.GameStore(args.games_dir, g["game_id"]).load_state()["status"] == tour.IN_PROGRESS
    )
    print(f"大会ID: {plan['tournament_id']}（全{len(plan['games'])}局、残り{remaining}局）")
    if not _confirm_real_cli(selected, remaining, rules, args.yes):
        return EXIT_CONFIG
    players = _players(selected, rules)

    def after_game(state: dict[str, Any]) -> None:
        _print_game_summary(state)
        stats.write_results(args.games_dir, args.results_dir, plan["tournament_id"])

    tour.run_tournament(
        args.games_dir, plan, players, rules,
        on_event=_print_event, before_game=_bind_workdir, after_game=after_game,
    )
    _, ranking = stats.write_results(args.games_dir, args.results_dir, plan["tournament_id"])
    print(stats.format_ranking(ranking))
    print(f"結果: {os.path.join(args.results_dir, 'matches.csv')}, {os.path.join(args.results_dir, 'ranking.csv')}")
    return EXIT_OK


def cmd_results(args: argparse.Namespace) -> int:
    _, ranking = stats.write_results(args.games_dir, args.results_dir, args.tournament)
    if not ranking:
        print("集計できる対局がない")
        return EXIT_OK
    print(stats.format_ranking(ranking))
    return EXIT_OK


def cmd_list_models(args: argparse.Namespace) -> int:
    models, _ = load_config(args)
    for m in models:
        flag = "" if m.enabled else " (無効)"
        print(f"{m.id}\tprovider={m.provider}\tmodel={m.model}\tsandbox={m.sandbox}{flag}")
    return EXIT_OK


def cmd_validate(args: argparse.Namespace) -> int:
    models, rules = load_config(args)
    print(f"設定OK: モデル{len(models)}件、反則上限{rules.foul_limit}、技術リトライ上限{rules.technical_retry_limit}")
    ok = True
    for m in models:
        try:
            argv = ai_runner.resolve_command(m.command, m.model)
            exe = argv[0]
        except (FileNotFoundError, ai_runner.ConfigError) as exc:
            if m.enabled:
                print(f"NG {m.id}: {exc}")
                ok = False
            else:
                print(f"SKIP {m.id}（無効）: {exc}")
            continue
        # version_command は --version 等の課金のない呼び出しだけを想定している
        version = ai_runner.AIPlayer(m).cli_version() if m.version_command else None
        flag = "" if m.enabled else "（無効）"
        print(f"OK {m.id}{flag}: {exe} version={version or '未取得'} prompt_via={m.prompt_via} sandbox={m.sandbox}")
    if args.live:
        selected = [m for m in models if m.enabled]
        unrestricted = [m.id for m in selected if not m.is_mock and m.sandbox != "restricted"]
        if unrestricted and not args.allow_unrestricted:
            print(f"サンドボックス制限を確認できていないモデル: {', '.join(unrestricted)}")
            print("検証目的で呼び出す場合のみ --allow-unrestricted を付ける")
            return EXIT_CONFIG
        if not _confirm_real_cli(selected, 0, rules, args.yes):
            return EXIT_CONFIG
        # 疎通確認も空の作業ディレクトリで実行する
        work_dir = os.path.abspath(
            os.path.join(args.games_dir, "_validate", datetime.now().strftime("%Y%m%d-%H%M%S"))
        )
        os.makedirs(work_dir, exist_ok=True)
        board_text = game.format_board(game.initial_board())
        for m in selected:
            attempt = ai_runner.AIPlayer(m, rules.default_timeout_sec, cwd=work_dir).ask(board_text, BLACK)
            if attempt.error_type:
                print(f"LIVE NG {m.id}: {attempt.error_type} {attempt.error_detail}")
                ok = False
            else:
                kind = ai_runner.classify_answer(attempt.answer or "")
                legal = attempt.answer in game.legal_moves(game.initial_board(), BLACK)
                print(f"LIVE {m.id}: 回答={attempt.answer!r} 形式={kind} 合法={legal} {attempt.elapsed_sec:.1f}秒")
    return EXIT_OK if ok else EXIT_RUNTIME


def setup_logging(games_dir: str) -> None:
    """運用ログ（ファイル置換のリトライなど）を games/_logs/ai-othello.log に残す。"""
    logger = logging.getLogger("ai_othello")
    for old in list(logger.handlers):
        if getattr(old, "_ai_othello", False):
            logger.removeHandler(old)
            old.close()
    logger.setLevel(logging.INFO)
    try:
        log_dir = os.path.join(games_dir, "_logs")
        os.makedirs(log_dir, exist_ok=True)
        handler: logging.Handler = logging.FileHandler(os.path.join(log_dir, "ai-othello.log"), encoding="utf-8")
    except OSError:
        handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler._ai_othello = True  # type: ignore[attr-defined]
    logger.addHandler(handler)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="main.py", description="AIモデル同士のオセロ対戦")
    parser.add_argument("--config", default=os.path.join("config", "models.yaml"))
    parser.add_argument("--rules", default=os.path.join("config", "rules.yaml"))
    parser.add_argument("--games-dir", default="games")
    parser.add_argument("--results-dir", default="results")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("play", help="1局だけ対局する")
    p.add_argument("--black")
    p.add_argument("--white")
    p.add_argument("--resume", metavar="GAME_ID")
    p.add_argument("--yes", action="store_true", help="実CLI使用の確認を省略する")
    p.add_argument("--allow-unrestricted", action="store_true", help="サンドボックス未確認のCLIを検証目的で使う")
    p.set_defaults(func=cmd_play)

    p = sub.add_parser("tournament", help="総当たり大会")
    p.add_argument("--models", help="カンマ区切りのモデルID（省略時は有効な全モデル）")
    p.add_argument("--games-per-side", type=int)
    p.add_argument("--resume", metavar="TOURNAMENT_ID")
    p.add_argument("--retry-aborted", action="store_true", help="技術中断した対局を別IDで再対局する")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_tournament)

    p = sub.add_parser("results", help="成績を集計・表示する")
    p.add_argument("--tournament", metavar="TOURNAMENT_ID")
    p.set_defaults(func=cmd_results)

    p = sub.add_parser("list-models", help="設定済みモデルの一覧")
    p.set_defaults(func=cmd_list_models)

    p = sub.add_parser("validate", help="設定とCLIの確認")
    p.add_argument("--live", action="store_true", help="各モデルに1手だけ実際に打たせる（課金の可能性あり）")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--allow-unrestricted", action="store_true", help="サンドボックス未確認のCLIを検証目的で呼ぶ")
    p.set_defaults(func=cmd_validate)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    setup_logging(args.games_dir)
    try:
        return args.func(args)
    except (ai_runner.ConfigError, ValueError, yaml.YAMLError) as exc:
        print(f"設定エラー: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except tour.StateError as exc:
        print(f"保存データの不整合のため停止: {exc}", file=sys.stderr)
        return EXIT_RUNTIME
    except KeyboardInterrupt:
        print("\n中断しました。確定済みの状態から再開できます（play --resume / tournament --resume）。", file=sys.stderr)
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())
