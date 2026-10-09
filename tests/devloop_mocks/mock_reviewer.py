"""devloop テスト用のモックレビュー担当（AIは呼ばない）。

--scenario の JSON 配列から、呼び出し回数（--counter）に応じた1要素を選ぶ。
要素のキー:
  review   この値を JSON にして標準出力に出す
  raw      この文字列をそのまま出す（不正なJSONの再現）
  touch    作成・上書きするファイル（レビュー担当による変更の再現）
  sleep    秒数だけ待つ
  exit     この終了コードで終わる
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mock_implementer import pick  # noqa: E402


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--scenario", required=True)
    p.add_argument("--counter", required=True)
    p.add_argument("--prompt-out")
    args = p.parse_args()
    # 親プロセスは標準入力を UTF-8 で書く。Windows の既定（cp932）で読むと文字化けして書き出せない。
    prompt = sys.stdin.buffer.read().decode("utf-8")
    if args.prompt_out:
        # バイナリで書く。テキストモードだと Windows で改行が CRLF に変換され、受け取った内容と一致しない。
        with open(args.prompt_out, "wb") as f:
            f.write(prompt.encode("utf-8"))
    step = pick(args.scenario, args.counter)
    if "sleep" in step:
        time.sleep(step["sleep"])
    for path in step.get("touch", []):
        with open(path, "w", encoding="utf-8") as f:
            f.write("changed by mock reviewer\n")
    if "raw" in step:
        print(step["raw"])
    elif "review" in step:
        print(json.dumps(step["review"], ensure_ascii=False))
    return int(step.get("exit", 0))


if __name__ == "__main__":
    sys.exit(main())
