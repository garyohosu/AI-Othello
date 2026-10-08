"""テスト用のモックAI CLI。

標準入力でプロンプトを受け取り、--actions で指定した動作をする。
--actions は「,」区切りで、--counter ファイルを使って呼び出し回数ごとに
動作を切り替える（最後の動作は以後繰り返す）。

動作:
  legal     合法手の先頭（なければ PASS）
  illegal   既に石があるマスの座標（必ず違法座標）
  pass      PASS
  format    説明付きの回答（形式違反）
  lower     小文字の座標（形式違反）
  empty     何も出力しない
  json      合法手を JSON で返す（使用量付き）
  badjson   壊れた JSON
  exit      終了コード 1 で終了
  auth      認証エラーのメッセージを出して終了コード 1
  sleep     --seconds 秒待ってから合法手
  answer:X  X をそのまま出力
  env:NAME  環境変数 NAME の値を出力

プロンプトは既定で標準入力から読む。--prompt-file / --prompt を指定した場合は
そちらから読む（実CLIのファイル渡し・引数渡しの再現用）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import game  # noqa: E402


def read_prompt(prompt_file: str | None, prompt_arg: str | None) -> tuple[game.Board, str]:
    if prompt_file:
        with open(prompt_file, encoding="utf-8") as f:
            text = f.read()
    elif prompt_arg is not None:
        text = prompt_arg
    else:
        text = sys.stdin.read()
    color = game.BLACK if f"あなたの色: 黒" in text else game.WHITE
    board_text = text.split("盤面:\n", 1)[1]
    return game.parse_board(board_text), color


def next_action(actions: list[str], counter_path: str | None) -> str:
    if not counter_path:
        return actions[0]
    count = 0
    if os.path.exists(counter_path):
        with open(counter_path, encoding="utf-8") as f:
            count = int(f.read().strip() or 0)
    with open(counter_path, "w", encoding="utf-8") as f:
        f.write(str(count + 1))
    return actions[min(count, len(actions) - 1)]


def main() -> int:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--actions", default="legal")
    parser.add_argument("--counter")
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--prompt-file")
    parser.add_argument("--prompt")
    args = parser.parse_args()

    board, color = read_prompt(args.prompt_file, args.prompt)
    action = next_action(args.actions.split(","), args.counter)
    moves = game.legal_moves(board, color)
    best = moves[0] if moves else "PASS"

    if action == "legal":
        print(best)
    elif action == "illegal":
        occupied = next(
            game.index_to_coord(r, c)
            for r in range(8)
            for c in range(8)
            if board[r][c] != game.EMPTY
        )
        print(occupied)
    elif action == "pass":
        print("PASS")
    elif action == "format":
        print(f"{best}に打ちます")
    elif action == "lower":
        print(best.lower())
    elif action == "empty":
        pass
    elif action == "json":
        print(json.dumps({
            "result": f"\n{best}\n",
            "model": "mock-model-1",
            "usage": {"input_tokens": 120, "output_tokens": 2},
            "total_cost_usd": 0.0001,
        }))
    elif action == "badjson":
        print('{"result": "D3"')
    elif action == "exit":
        print("something failed", file=sys.stderr)
        return 1
    elif action == "auth":
        print("Error: not logged in. Please run login.", file=sys.stderr)
        return 1
    elif action == "sleep":
        time.sleep(args.seconds)
        print(best)
    elif action.startswith("env:"):
        print(os.environ.get(action.split(":", 1)[1], ""))
    elif action.startswith("answer:"):
        print(action.split(":", 1)[1])
    else:
        print(f"unknown action {action}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
