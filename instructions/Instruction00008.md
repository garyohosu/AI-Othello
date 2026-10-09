# Instruction00008 — Claude/Codex実CLIの最小結合試験（別途承認必須）

発行日: 2026-10-10
担当: ローカルのClaude Code
前回: `instructions/Result00007.md`
結果報告: `instructions/Result00008.md`

## 目的

`tools/devloop/autopilot.py` がモックで200テスト成功したので、次は使い捨てGitクローンでClaude実装担当1回とCodexレビュアー1回を使った**最小の実CLI結合試験**に進む。重点は「実際にstdinをClaudeが受け付けるか」「CodexのJSONが厳密に読めるか」「機械的pytestと実際のGit差分が報告と一致するか」。モックテストを増やすだけで試験を先送りしない。

## 最重要: この指示書の存在は費用の承認ではない

**本指示書を読んだだけで `claude -p` や `codex exec` を実行してはいけない。**

実行してよいのは、ユーザーがこの指示書とは**別の明示的なメッセージで**以下を許可した場合のみ:
- 実CLIのモデル呼び出し（Claude最大1回、Codex最大1回）
- Claudeへの `--max-budget-usd 1` 設定（ただし2モデル合計の金額上限は保証されない）
- 使い捨てクローンの専用ブランチ上でのローカルcommit（pushなし）

承認がない場合は、無課金の準備・dry-runだけを行い、**実AIを呼ばずに停止する**。承認の有無を推測しない。Claude Codeで本指示書を読むための通常の会話そのものを、devloop内のモデル呼び出し承認と取り違えない。

## 1. ローカル同期と試験環境

1. `C:\project\AI-Othello` の `git status` を確認し、`origin/main` を `git fetch`。ユーザーの変更を破棄しない。`Instruction00008.md` と `Result00007.md` を確認する。
2. 元のリポジトリではdevloopの実CLI試験を実行しない。新しい使い捨てクローン（例: `C:\project\AI-Othello-devloop-trial`）を作り、`devloop-trial` という専用ブランチへ移動する。既存の同名ディレクトリがあるなら上書きせず、安全な別名を選ぶ。
3. 元のローカルリポジトリの未追跡ファイル、`.devloop/`、`devloop.yaml`、認証情報等をクローンへコピーしない。グローバル設定やOSの権限を変更しない。
4. 試験用指示書 `instructions/Instruction00010.md` を**試験用クローン内にだけ**作成する。内容例: 小さな純粋関数 `clamp01(x)` を新しいファイル `devloop_smoke.py` に実装し、境界値と範囲外の値を検証する `tests/test_devloop_smoke.py` を作る。既存コードに影響させず、依存関係を変更しない。実装担当が `instructions/Result00010.md` を新規作成することも明記する。
5. 試験用指示書をクローンの専用ブランチにローカルcommitし、devloop起動前の作業ツリーをクリーンにする。**GitHubへのpush禁止**。
6. 試験用の `devloop.yaml` と `queue.yaml` はGit管理外に作り、使い捨てであることを明記する。対象クローンの `tools/devloop/config.example.yaml` と `queue.example.yaml` の実際のキー名を利用する。

## 2. 安全設定（明示的に承認された場合のみ）

- `dry_run: false`, `allow_real_cli: true`, `require_clean_worktree: true`, `allow_delete: false`
- `max_loops: 1`, `max_total_calls: 2`, `max_same_failure: 1`; キューはタスク1件（`Instruction00010.md`）、`max_tasks: 1`、`max_total_calls: 2`、`max_elapsed_sec` は有限値（例: 1200秒）。
- キューの `allow_commit: true`、`allow_push: false`。`--commit` は利用可、`--push` は一切付けない。
- Claude実装担当: `-p`、stdinでUTF-8プロンプト、`--tools Read,Edit,Write,Glob,Grep`、`--permission-mode acceptEdits`、`--permission-prompts none`、`--no-session-persistence`、`--strict-mcp-config`、`--disable-slash-commands`、`--max-budget-usd 1`。Bashなどの実行ツールは与えない。1回のタイムアウトを短め（例: 600秒）にする。
- Codexレビュアー: `codex exec -s read-only --ephemeral --skip-git-repo-check --color never --output-schema {schema_file} -`、stdinでプロンプト、厳密なJSONを標準出力から取り出す。1回のタイムアウトは短め（例: 300秒）。
- **cwdやacceptEditsのみではクローン外への書き込みが防げると断言しない。** 実装ツール権限が想定と異なる、外部パス編集を求められる、レビュアーが変更したなどの兆候があれば停止する。
- `--max-budget-usd 1` はClaude側の設定であり、Codexを含む合計費用の保証ではない。CodexのCLIに金額上限を確認できていないため、**Codexは1回のみ**とする。費用が確実に無料・1ドル以内などと報告しない。

## 3. 課金方式・認証の事前確認

**実CLI起動前に**利用方式を確認する（秘密情報の値は表示・保存しない）。
- `ANTHROPIC_API_KEY`、`OPENAI_API_KEY` 等が環境に設定されているかは**存在の有無のみ**を確認する。値を表示しない。Claude Pro等の定額ログインがあっても、設定されたAPIキーを経由して別課金になる可能性があるので、APIキー使用が疑われる場合は停止して方式を明記し、再承認を求める。APIキーを勝手に無効化・削除しない。
- Codexのログイン方式（ChatGPTアカウント利用かAPIキーか）が安全に確認できなければ、**不明として停止**。資格情報ファイルの中身を読み出さない。
- 承認済みでも、想定外の新しい課金経路や権限の拡大が必要なら実行を見送り、Resultへ理由を記録する。

## 4. 実行手順

1. クローンで `py -m pytest -q tests/test_devloop.py tests/test_autopilot.py` を実行し、ベースラインを記録。
2. 実AIを呼ばない `py -m tools.devloop.autopilot --repo . --queue <queue.yaml> --config <devloop.yaml> --dry-run` で、Claude/Codexの実行コマンド、1件2呼び出し制限、commit可・push不可を確認する。
3. **明示的な別途承認があり、認証・課金の確認も通過した場合だけ** `--execute --allow-real --commit` で監督ランナーを**1回だけ**実行。プロセスのリトライや再実行は、追加のモデル呼び出しが発生するなら再承認が必要。
4. `.devloop/autopilot.json`、`.devloop/state.json`、ログ、実測されたモデル呼び出し回数、終了コード、Result00010、Git差分、テスト結果、レビューJSON、commit SHAを確認する。秘密情報は記録しない。
5. `complete` なら試験成功。途中で停止した場合は**停止理由をそのまま報告**し、CLIオプションやアダプタを場当たり的に緩めて追加実行しない。
6. 試験用クローンはユーザーの追跡調査が終わるまで自動削除しない。GitHubへの試験ブランチpushは禁止。

## 5. Resultと通常のコミット

- 元の `instructions/Result00008.md` を新規作成し、試験実施・未実施、承認の有無、CLI/モデル・認証方式（秘密値なし）、実呼び出し回数、各プロセス終了コード、レビューJSONの解析、pytest、変更ファイル、Git commitの有無、停止理由、費用の**実際に確認できた範囲だけ**、次の改善点を自足した形で記載する。
- **承認なしの場合は「実CLI未実施」と明記**。未実行のものを成功と書かない。
- 元リポジトリに対するResult00008のcommit/pushは、従来のClaude Code通常作業として行ってよい。ただしユーザーの未コミット変更を破壊しない。試験用クローンからのpushは禁止。
- 画面への報告はResult00008へのリンクと結果、コミットSHA、承認待ちの有無だけ。ログ全文をユーザーにコピーさせない。

## 完了条件

1回の実AI結合試験で「実装→テスト→Codexレビュー→合格時の専用ブランチcommit」まで到達したか、または再現可能な停止理由が明確になっていること。試験が成功するまで追加の有料呼び出しを無制限に繰り返すことは禁止する。次段階の複数タスク連続実行は、本試験の結果を確認してから判断する。
