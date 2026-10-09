"""devloop テスト用のモック実装担当（AIは呼ばない）。

--scenario の JSON 配列から、呼び出し回数（--counter）に応じた1要素を選んで実行する。
最後の要素は以後繰り返す。要素のキー:
  write_result (既定 true)  結果報告を --result に書く
  result_text               結果報告の本文（省略時は見出し付きの定型文）
  test_status               "pass" / "fail"。作業ツリーの status.txt に 0 / 1 を書く
  touch                     作成・上書きするファイルの一覧
  delete                    削除するファイルの一覧
  commit                    true なら git commit する（禁止操作の再現）
  print                     標準出力に出す文字列
  sleep                     秒数だけ待つ
  exit                      この終了コードで終わる
"""

import argparse
import json
import os
import subprocess
import sys
import time


def pick(scenario_path, counter_path):
    with open(scenario_path, encoding="utf-8") as f:
        steps = json.load(f)
    count = 0
    if os.path.exists(counter_path):
        with open(counter_path, encoding="utf-8") as f:
            count = int(f.read().strip() or 0)
    with open(counter_path, "w", encoding="utf-8") as f:
        f.write(str(count + 1))
    return steps[min(count, len(steps) - 1)]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--scenario", required=True)
    p.add_argument("--counter", required=True)
    p.add_argument("--result", required=True)
    p.add_argument("--instruction", required=True)
    args = p.parse_args()
    sys.stdin.buffer.read()  # プロンプト（使わない）
    step = pick(args.scenario, args.counter)

    if "sleep" in step:
        time.sleep(step["sleep"])
    if "print" in step:
        print(step["print"])
    for path in step.get("touch", []):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("changed by mock implementer\n")
    for path in step.get("delete", []):
        os.remove(path)
    if "test_status" in step:
        with open("status.txt", "w", encoding="utf-8") as f:
            f.write("0" if step["test_status"] == "pass" else "1")
    if step.get("write_result", True):
        text = step.get("result_text") or (
            f"# 結果報告（モック）\n\n指示書: {args.instruction}\n\n## テスト\n- モックのため未実施\n"
        )
        with open(args.result, "w", encoding="utf-8") as f:
            f.write(text)
    if step.get("commit"):
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(["git", "-c", "user.name=mock", "-c", "user.email=mock@example.com",
                        "commit", "-qm", "mock commit"], check=True)
    return int(step.get("exit", 0))


if __name__ == "__main__":
    sys.exit(main())
