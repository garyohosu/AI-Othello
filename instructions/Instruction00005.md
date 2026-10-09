# Instruction00005 — 実CLI結合テストの事前準備（実AI呼び出し禁止）

発行日: 2026-10-10
対象: AI-Othello / `tools/devloop/`
実行担当: ローカルの Claude Code
結果報告: `instructions/Result00005.md`

## 目的

モックの文字コード修正（コミット `6773908`）と `instructions/Result00004.md` を引き継ぎ、Claude Code（実装担当）・Codex（レビュー担当）を使う最小構成の結合テストの**実行準備だけ**を終える。

**この指示書は実AIへの問い合わせ・課金・本番の結合テストを許可しない。** CLIの `--help` / `--version`、ローカルのpytest、dry-run、Git操作は実行してよい。追加費用が発生し得る `claude -p`、`codex exec` 等の実行は禁止する。

## 作業1 — 既存のResult00004を保全・コミットして同期

1. ローカル `C:\project\AI-Othello` で `git status`、HEAD、`origin/main` を確認する。
2. ユーザー報告では `instructions/Result00004.md` が未追跡。存在と内容を確認し、**このファイルだけ**をコミットする。既存ファイルを上書き・削除しない。すでにコミット済みなら重複コミットしない。
3. `git fetch origin` 後、リモートの最新指示書を取り込む。ローカルの未コミット変更があれば保全し、勝手に破棄しない。安全に `git rebase origin/main` できる場合だけ実行し、競合・履歴不整合時は停止して報告する。force pushは禁止。
4. すでにリモートにある本指示書 `Instruction00005.md` を編集・上書きしない。`Instruction00004.md` を新規に捏造しない。00004番は既存の `Result00004.md` による臨時作業報告に使用済みである。
5. 前記の同期に成功し、余分な変更がなければ通常の `git push origin main` を行う。

## 作業2 — CLIオプションの実在確認（モデルは呼ばない）

- `claude --version` / `claude --help`、`codex --version` / `codex --help` / `codex exec --help` を調べる。Windowsの実行体（exe/cmd/ps1）と呼び出し方法も確認する。CLIをインストール・更新しない。
- Claude側の `-p`、`--tools`、`--permission-mode`、`--permission-prompts`、`--max-budget-usd`、`--no-session-persistence` 等の有無・構文を確認する。**ヘルプ記載と実動作確認は区別する。** 存在しないフラグを本番用設定に残さない。
- Codex側の `exec`、`-s read-only`、`--ephemeral`、`--output-schema`、標準入力 `-` の有無・構文を確認する。Codexの金額上限設定が存在しない場合は「上限を強制できない」と記す。
- Claude Pro/Codexのサブスクリプション利用と、追加従量課金の可能性を混同しない。ヘルプだけでは課金額・総額上限・権限分離は保証できない。認証トークンや秘密情報の表示は禁止。

## 作業3 — 安全な最小結合テストの計画

実行用計画（手順とコマンド案）を `instructions/Result00005.md` に具体的に記載する。

- 実行環境は**使い捨ての別クローン／別ブランチ**。作業終了後に削除可能で、元のリポジトリを変更しない構成とする。
- 最初のテストは `max_loops: 1`、`max_total_calls: 2`（Claude 1回、Codex 1回を上限）、`max_same_failure: 1`。専用の小さなテスト課題を用い、依存関係変更・ファイル削除・外部送信・pushは禁止。
- 実装担当は `Read,Edit,Write,Glob,Grep` だけを候補とし、`Bash` などのコマンド実行権限は付けない。編集許可は `acceptEdits` を候補とする。ただし **CLIのcwdや許可ツールだけでは作業ディレクトリ外への書き込みを遮断できるとは限らない**。OSレベルの隔離や実際の境界を別途評価し、保証できないものを「安全確認済み」としない。
- レビュアーCodexは `read-only` とし、変更前後のGit差分・未追跡ファイルの検査で書き込みがないことを機械的に確認する。
- Claudeに `--max-budget-usd 1` を指定できるか確認するが、これは**案であり課金承認ではない**。Codexを含めた総額1ドル保証など、根拠のない説明をしない。
- プロンプト入力／標準出力の形式、JSON Schemaの妥当性、CLI終了コード、タイムアウト、権限拒否時の停止、費用ログの限界、後片付けの手順を整理する。
- 実行前に、ユーザーが判断すべき残課題と追加費用の可能性を明記する。

## 作業4 — 課金なしの検証

1. 既存の `tools/devloop/config.example.yaml` と `docs/devloop.md` を照合する。フラグがヘルプと矛盾する場合は、**実AIを呼ばずに**安全な設定例と説明のみ修正してよい。大きな仕様変更は禁止。
2. `py -m pytest -q tests/test_devloop.py` を実行。可能なら `py -m pytest -q` も実行し、成功数・失敗数・skip数・警告とコマンドを記録する。
3. symlinkテストの `56 passed` と `55 passed, 1 skipped` の差は、skip条件や環境情報を読んで調査する。管理者権限の昇格やWindowsの開発者モード変更は行わない。原因が確認できない場合はそのまま記す。
4. テスト用設定の `dry_run: true`、`allow_real_cli: false` を維持し、`max_loops: 1`、`max_total_calls: 2` の計画表示を確認する。dry-runではAIプロセスや課金が起きず、状態・結果ファイルを生成しないことを検証する。
5. テスト準備用クローンを作ってよいが、**その中でも実AI実行は禁止**。既存の秘密情報・未追跡ファイルをクローンにコピーしない。

## 作業5 — Result作成・コミット・push

- `instructions/Result00005.md` を**新規作成**する。実施内容、変更ファイル、確認したCLIのバージョンと実際に確認できたオプション、実行したコマンド、pytestとdry-runの結果、未検証事項、課金の可能性、残る承認事項、次の具体的な手順を、**この1ファイルだけで判断できる**ように記録する。
- 未実行の実CLI結合テストを実行済み・合格と記載しない。「実AI呼び出し0回」を明記する。
- 作業範囲内のファイルとResultをコミットし、通常の `git push origin main` まで自律的に行う。Git履歴改変・force pushは禁止。push失敗時は成功と偽らずResultと画面に理由を残す。
- **端末での最終回答は、Result00005のGitHubリンク、コミットSHA、実AI呼び出し0回、および必要な人間の承認事項だけ**にする。ユーザーに長文ログのコピーを求めない。

## 承認の境界（厳守）

通常の調査、ローカルのテスト、dry-run、作業指示の範囲内での編集・コミット・push、Result記録は追加承認不要。

実モデルの呼び出し、費用が発生し得る操作、グローバルな権限緩和、OS設定変更、認証情報の取り扱い、破壊的変更は**今回の許可範囲外**。必要ならResultに具体的な判断事項を書いて停止する。
