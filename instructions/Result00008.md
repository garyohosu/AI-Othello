# Result00008 — 実CLI結合試験（使い捨てクローン）: 準備まで完了、実AI起動は権限拒否により未実施

対応する指示書: [Instruction00008.md](./Instruction00008.md)
前回: [Result00007.md](./Result00007.md)
実施日: 2026-10-10
実行担当: Claude Code（Claude Haiku 5.5）

## 0. 要約
- **実CLI結合試験は未実施。** 実AIを呼んだ回数は **0回**。
- 理由: 実行コマンド（監督ランナーの `--execute --allow-real --commit`）が、Claude Code の自動モードの分類器に **「Create Unsafe Agents」として拒否された**。ユーザーの依頼と指示書の承認範囲内の作業だが、分類器の判断を回避する別経路は使っていない。
- 完了したこと: 認証状態の確認（秘密値なし）、使い捨てクローンの作成（push無効）、ベースラインテスト（80 passed）、試験用指示書のクローン内コミット、試験用設定とキューの作成、dry-run（副作用なし）。
- **元のリポジトリは変更していない**（Result00008 の追加のみ）。試験用クローンからのpushはしていない。

## 1. 認証・課金経路の確認（秘密値は表示・保存していない）

| 項目 | 結果 | 判断 |
|---|---|---|
| `ANTHROPIC_API_KEY` | 未設定 | Claude の API 従量課金は経由しない |
| `claude auth status` | ログイン済み、方式 `claude.ai`、プラン `pro` | 定額プラン経由 |
| `CLAUDE_CODE_OAUTH_TOKEN` | 未設定 | — |
| `OPENAI_API_KEY` | **設定あり** | Codex が API キーで課金される可能性があるため、試験プロセス内だけ `unset` する方針にした（キー自体は削除・変更していない） |
| `codex login status` | `Logged in using ChatGPT` | ChatGPT アカウント経由。APIキー方式ではない |
| `CODEX_API_KEY` | 未設定 | — |

- 注意: Codex がどの認証を優先するかは、`OPENAI_API_KEY` の存在で変わる可能性を完全には否定できない。試験を行う場合は、そのシェルで `unset OPENAI_API_KEY` を実行してから起動する（本Resultの作成時点では、プロセスには一切渡していない）。
- 金額の上限は、Claude は `--max-budget-usd 1`（Claude 側の呼び出し予算。全体の保証ではない）、Codex は CLI に金額上限のオプションが確認されていないため保証なし。

## 2. 実施した手順

1. `git fetch`、`origin/main` へ fast-forward（`9ab739a`）。ローカルに未コミット変更はなかった。
2. 使い捨てクローン `C:\project\AI-Othello-devloop-trial` を作成。
   - ブランチ `devloop-trial`、push 先は `DISABLED_NO_PUSH` に設定（誤 push 防止）。
   - `.devloop/` や認証情報はコピーしていない。
3. ベースラインテスト（クローン内）: `py -m pytest -q tests/test_devloop.py tests/test_autopilot.py` → **80 passed**（78.79秒）。
4. 試験用指示書 `instructions/Instruction00010.md` をクローン内にだけ作成し、クローンの `devloop-trial` にローカルcommit（`25b2cd7`）。内容は `devloop_smoke.py` の `clamp01(x)` と、その境界値テスト。結果報告は `Result00010.md` を新規作成する指定。
5. 試験用の設定とキューは、リポジトリの外（スクラッチパッド）に配置。
   - 設定: `dry_run: false`、`allow_real_cli: true`、`max_loops: 1`、`max_total_calls: 2`、`max_same_failure: 1`、`require_clean_worktree: true`、`allow_delete: false`。テストは `tests/test_devloop_smoke.py` のみ。
   - Claude 実装担当: `-p`（プロンプトは stdin）、`--tools Read,Edit,Write,Glob,Grep`、`--permission-mode acceptEdits`、`--permission-prompts none`、`--no-session-persistence`、`--strict-mcp-config`、`--disable-slash-commands`、`--max-budget-usd 1`、タイムアウト600秒。Bash は与えていない。
   - Codex レビュア: `exec -s read-only --ephemeral --skip-git-repo-check --color never --output-schema {schema_file} -`、タイムアウト300秒。
   - キュー: タスク1件（`Instruction00010.md`）、`max_total_calls: 2`、`max_elapsed_sec: 1200`、`allow_commit: true`、`allow_push: false`。
6. dry-run（クローン内、`--execute` なし）: 計画どおり表示。AI起動なし、`.devloop/` 作成なし、作業ツリーはクリーン、終了コード 0。
7. 実行（`--execute --allow-real --commit`、`OPENAI_API_KEY` を除いた環境）を試みたが、**Claude Code の自動モード分類器により拒否された**（理由欄: 「Create Unsafe Agents」）。拒否後、別の方法で同じ処理を起動する試みは行っていない。

## 3. 試行回数の集計

| 試行 | 実AI呼び出し | 結果 |
|---|---|---|
| 1 | 0（起動前に拒否） | 未実施 |
| 2・3 | 0 | 未実施 |
| 合計 | **0 / 上限6** | — |

## 4. 未解決事項・次の判断

1. **実行権限が必要。** 次のどちらかが必要。
   - (a) ユーザーが自分のターミナルで、下記の手順を実行する。
   - (b) 本セッションの権限設定で、この実行を許可するルールを追加する。その場合は範囲（クローンのパス、`--execute --allow-real --commit`、キューのタスク1件）を明記する。
2. **Codex の認証経路の最終確認。** `OPENAI_API_KEY` が Codex に使われないことを、ユーザーが確認するか、起動前に `unset` する。
3. **試験の結果は未知。** 「stdin の UTF-8 プロンプトを Claude が受け付けるか」「Codex の JSON が `--output-schema` で strict に得られるか」は、実行して初めて分かる。

## 5. ユーザーが実行する場合の手順（参考）

```bash
# 1. このシェルだけで API キーを外す（設定ファイルは変更しない）
unset OPENAI_API_KEY
# 2. 使い捨てクローンで実行（push は無効化済み）
cd /c/project/AI-Othello-devloop-trial
SP="/c/Users/garyo/AppData/Local/Temp/claude/C--project-AI-Othello/a46af0ef-5e10-4cb3-bbd2-712273eb1f4c/scratchpad"
py -m tools.devloop.autopilot --repo . --queue "$SP/trial-queue.yaml" --config "$SP/trial-devloop.yaml" --execute --allow-real --commit
```

完了後に確認する項目: 終了コード、`.devloop/autopilot.json`、`instructions/Result00010.md` の有無、`git log --oneline -3`、`git status`、Codex の出力（`.devloop/log.jsonl`）。その上で、次の判断（デバッグ・再試行）をする。

## 6. 次の改善点
- 試験は、スクラッチパッドにある設定とキューを使えば再現できる。
- 試験後、`.devloop/` に含まれる実CLIの生出力（stdout/stderr）を読み、Claude の stdin 受付とCodexのJSONを確認する。
