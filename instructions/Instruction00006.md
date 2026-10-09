# Instruction00006 — devloopのstdin対応と無課金の回帰検証

発行日: 2026-10-10
担当: ローカルのClaude Code
結果報告: `instructions/Result00006.md`
引継ぎ: `instructions/Result00005.md`（コミット `f7b58c4`）

## 目的

実CLI結合テストに進む前に、Windowsのコマンドライン引数長制限に依存しているClaude Codeの長文プロンプト渡しを改善し、UTF-8・日本語・長文をローカルモックで確認する。Codexのレビュー結果取得方法は現状の標準出力方式を維持する。

**本作業は実AI呼び出し・有料テストを一切許可しない。** `claude -p` と `codex exec` は実行しない。CLIの `--help` / `--version`、pytest、モック、dry-runは許可する。

## 1. リポジトリの同期

1. `C:\project\AI-Othello` で `git status` と現在のHEADを確認し、ユーザーの未コミット変更を保護する。
2. `git fetch origin` で最新の `main` を確認する。リモートに追加済みの本指示 `instructions/Instruction00006.md` を取り込み、先行する `Result00005.md` の状態を確認する。ローカル作業がなければfast-forwardで同期する。
3. 既存のInstruction/Resultファイルは上書きしない。競合、予期しない差分、リモートより古い履歴を誤って上書きするおそれがある場合は停止してResultへ状況を記す。force pushは禁止。

## 2. Claudeのプロンプトをstdinで渡す

確認した現状:
- `tools/devloop/adapters.py` の `run_role()` は、設定コマンドに `{prompt}` がなければプロンプトを標準入力へ渡す仕組みを**すでに持っている**。
- `run_process()` は `subprocess.Popen(..., encoding="utf-8")` と `communicate(stdin_text)` を使う。
- 一方 `tools/devloop/config.example.yaml` の実装担当コマンドは `["claude", "-p", "{prompt}", ...]` なので、長い日本語プロンプトがWindowsのコマンドライン引数に展開される。
- `claude -p` にプロンプト引数を指定せず、stdinから渡す方式の**実CLIでの動作は未検証**。無課金のモックで保証できるのはアダプタの入出力契約までであり、Claude本体の挙動ではない。

作業:
1. `config.example.yaml` のClaude実装担当 `command` から `{prompt}` を取り除き、`-p` は残す。その他の許可ツール・権限制約は緩めない。
2. `docs/devloop.md` と設定コメントに「stdinへUTF-8で送る」「Windows長文対応」「Claude実CLIでの受付動作は未検証」と明記する。
3. `adapters.py` 本体への修正は、必要性がテストで証明された場合に限る。不要なリファクタリングは行わない。
4. `{prompt}` をargvで渡す方式を他用途で使えるように保つ場合も、既存の `.cmd/.bat` に関する安全チェックは維持する。
5. Claudeを使ってstdin方式を確認する目的であっても、実際の `claude -p` は起動しない。

## 3. 無課金の自動テストを拡充

実AI実行体を使わないダミープロセスや既存の `tests/devloop_mocks/` を用いて、最低限次を確認する。

- 日本語・改行・記号・絵文字を含むプロンプトが、UTF-8のまま**完全一致**で子プロセスへ届くこと。Windows cp932の既定値には依存しない。
- 十分長いプロンプト（例: 64KiB以上）が、argvではなくstdinに送られ、起動引数が長文化しないこと。子プロセス側で受信長・ダイジェストを検証してもよい。
- `-p` に `{prompt}` を含めない設定でも、期待どおり標準入力にプロンプトが送られること。
- 既存の `{prompt}` 引数方式と `.cmd/.bat` の拒否ルールが退行しないこと。
- stdin読み込み失敗、非ゼロ終了、タイムアウト時は既存の `technical_error` 停止に収束すること（適切な既存テストがあれば再利用）。
- dry-runは実AIプロセスを一切起動せず、作業ツリーを変更しないこと。
- `Codex` 側の標準入力 `-` とレビューJSONの標準出力取得は変更せず、既存テストで退行を確認する。

テスト用ダミーは実AIの実行ファイル名を装わない。外部API呼び出し、認証情報へのアクセス、ネットワーク通信をしない。

## 4. 実CLI試験用の設定案と停止条件

実際に起動するのではなく、次回のための**候補設定・操作手順**をResultに残す。

- 使用場所: 元リポジトリとは別の使い捨てクローンと専用ブランチ。
- 呼び出し上限: `max_loops: 1`、`max_total_calls: 2`（ClaudeとCodexを各最大1回）、`max_same_failure: 1`。
- Claude: `--tools Read,Edit,Write,Glob,Grep`、`--permission-mode acceptEdits`、`--permission-prompts none` を候補とし、Bash/外部コマンドは与えない。`--max-budget-usd 1` を候補に挙げるが、実効性未検証・総額保証なしと明記する。
- Codex: `-s read-only`、`--ephemeral`、`--output-schema`、プロンプトstdin、JSONを標準出力から取得する方式を現状維持する。`-o` の採用は初回結合テスト結果を踏まえて再評価する。
- CodexにはCLIの金額上限が確認されておらず、サブスクリプション利用枠と従量課金の扱いを含め**アカウント側の設定は未確認**と明記する。費用の強制上限を保証しない。
- `acceptEdits` やcwd指定だけでクローン外への書き込みを確実に防げるとみなさない。専用ユーザーやOS・VM側の隔離を検討し、最低限元リポジトリと認証情報を保護する。
- 本作業で `allow_real_cli: true` + `--allow-real` + `--execute` の組合せを実行しない。ユーザーの明示的な有料テスト承認が必要。

## 5. 実行する確認コマンドと受入れ条件

1. `py -m pytest -q tests/test_devloop.py`
2. `py -m pytest -q`
3. デフォルト安全設定によるdry-run（`py -m tools.devloop.controller --repo . --instruction instructions/Instruction00006.md --config tools/devloop/config.example.yaml --dry-run`）。ただしResult等の存在との整合は先に確認する。

追加テストを含むすべてのテストで失敗0を目標とする。従来の56件・176件からテスト総数が増えるのは正常。失敗が残ったら未解決として記録し、成功と偽らない。

dry-runではClaudeのコマンドラインにプロンプト本文が展開されず、stdin利用予定であることを確認する。これによって実Claudeのstdin対応が実証されたと主張しない。

## 6. 結果報告・Git運用

1. `instructions/Result00006.md` を新規作成し、次を自足した形で記録する: 変更ファイル、stdin移行の理由と設計、追加・既存テストの**実測**結果、実行コマンド、dry-run結果、CLI実機未検証項目、残る安全性・費用リスク、次に必要な承認。
2. **実AI呼び出し0回**であったことを明記する。
3. 通常作業のソース変更とResultをコミットし、`git push origin main` まで自律的に行う。force push・無関係な削除・履歴破壊は禁止。失敗したらResultと端末の最終回答に理由を記載する。
4. 最終回答は **Result00006へのGitHubリンク、コミットSHA、テストの結果、実AI呼び出し0回、未解決事項** だけを簡潔に通知する。ユーザーにログ全文を貼り付けさせない。

## 権限・禁止事項

通常のコード修正、pytest、モック、dry-run、Result作成、コミット・pushは承認を追加で求めなくてよい。一方、**実AIによるモデル応答を起こすCLI起動、従量課金操作、OS設定の変更、グローバルな権限緩和、秘密情報へのアクセス、破壊的Git操作は禁止**。実CLIテストの許可判断は今回の指示書に含まれない。
