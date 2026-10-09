# Result00004 — devloop モックの文字化け修正と、実CLI結合テストの計画

対応する指示書: なし（作業内容は対話で指示された。`Instruction00004.md` は作成していない）
実施日: 2026-10-10
実行担当: Claude Code（Claude Haiku 5.5）
作業環境: Windows 11 Pro 10.0.26300 / Git for Windows

## 0. 要約
- **完了。** devloop テストのモック2ファイルの修正をコミット `6773908` に記録した。コミットはこの1件だけ。
- 実CLI（Claude Code / Codex）は**呼び出していない**。課金を伴う操作は 0 件。
- テスト: `tests/test_devloop.py` を実行し **56 passed**（skip なし）。実行時間は約68秒。
- 次の作業（実CLI結合テスト）の手順と安全対策を §3 に整理した。実行は承認待ち。
- この Result ファイルは**未コミット**。コミットするかは指示があれば行う。

## 1. 実施内容

### 1.1 モック修正のコミット
- 対象: `tests/devloop_mocks/mock_reviewer.py`、`tests/devloop_mocks/mock_implementer.py`
- 原因（前回の報告より）: Windows の既定コードページ（cp932）で `sys.stdin.read()` が UTF-8 の日本語プロンプトを読んでいたため文字化けし、UTF-8 で書き出す際に `UnicodeEncodeError` で終了コード1になっていた。
- 修正: `sys.stdin.buffer.read()` を使う。`mock_reviewer.py` は `.decode("utf-8")` で明示的に UTF-8 として読む。`mock_implementer.py` は内容を使わないため読み捨てる。
- `tools/devloop/` 本体は変更していない。
- コミットメッセージ: `test: read mock stdin as UTF-8 bytes to fix Windows cp932 failures`（Co-Authored-By: Claude Haiku 5.5）

### 1.2 コミット後の git status
```
On branch main
Your branch is ahead of 'origin/main' by 1 commit.
nothing to commit, working tree clean
```
（この Result ファイルの作成前の状態。作成後は `instructions/Result00004.md` が未追跡として表示される。）

### 1.3 テスト結果
- 実行: `python -m pytest tests/test_devloop.py -q`
- 結果: `56 passed in 68.34s`
- 補足: 前回の報告では「55 passed, 1 skipped」だった（`test_symlink_path_is_rejected` が skip。この環境では symlink の作成権限がないため）。今回の実行では skip は出ていない。差の原因は確認していない。symlink の権限が環境ごとに違う可能性がある。
- 前回 Result00003 で残っていた「初回だけ21件失敗・原因不明」は、今回の修正で文字化けが原因と判明した。ただし「なぜ以前は再現しなかったか」は未確認。

## 2. 変更していないもの
- `tools/devloop/` 本体、オセロ本体、`dream.md`、既存の Result / Instruction ファイル。
- 実CLIの設定（`config.example.yaml` の `allow_real_cli: false`、`dry_run: true`）。

## 3. 次の作業: 実CLI結合テストの手順と安全対策（未実行・承認待ち）

### 3.1 目的
Claude Code（実装担当）と Codex（レビュー担当）を実際に起動し、devloop のループが端から端まで動くかを確認する。モックでは検証できない次の点が対象。
- 実CLIの引数（`claude -p`、`codex exec`）が正しく受け付けられるか
- 出力の取り方（最終回答だけが標準出力に出るか）
- レビュー結果が `schema.py` の検証を通るか
- 権限設定で、作業ディレクトリ外や許可外のコマンドが実行されないか

### 3.2 実行前に承認が必要な理由
- 実AIの呼び出しは API 利用料金（または契約枠）を消費する。
- 実装担当はファイルを編集する。使い捨ての環境で行わないと、このリポジトリの作業ツリーを壊すおそれがある。

### 3.3 推奨手順
1. **使い捨てのクローン**を作る（例: `C:\project\AI-Othello-devloop-trial`、新しいブランチ `devloop-trial`）。このリポジトリ本体では実行しない。
2. 簡単な指示書を1つ用意する（例: 小さな関数を1つ追加し、そのテストを書く）。`instructions/Instruction00001.md` の形式（5桁番号）に合わせる。
3. 設定を次のように絞る。
   - `dry_run: false`、`allow_real_cli: true`（実行時は `--allow-real` も必要）
   - `max_loops: 1`、`max_total_calls: 2`
   - `max_same_failure: 1`
4. まず `dry_run` で計画を表示し、コマンドラインを目視で確認する。
5. 承認を得てから実行する。実行後は `.devloop/log.jsonl` と `git status` / `git diff` を確認する。
6. 結果は Result ファイルに記録し、使い捨てのクローンは確認後に削除する。

### 3.4 安全対策（設定案）
- **権限**: 実装担当は `--tools Read,Edit,Write,Glob,Grep` に限定し、Bash を含めない。権限モードは `acceptEdits`。作業ディレクトリ外への書き込みが防がれるかは**未検証**。
- **レビュー担当**: `codex exec -s read-only`。読み取り専用サンドボックス。
- **費用上限**: Claude Code の `--max-budget-usd` は `--print` 時のみ有効とヘルプに記載されている。付けるかは承認時に決める。
- **呼び出し回数**: `max_total_calls: 2`。超えたら停止する。
- **タイムアウト**: 実装 1800秒、レビュー 600秒（設定例どおり）。
- **秘密情報**: adapters.py の既存のマスク処理を使う。ログに API キーを残さない。
- **停止条件**: 機械チェック失敗、同じ失敗の繰り返し、タイムアウト、想定外の変更ファイル（`safety.py` の保護対象）のいずれかで止める。

### 3.5 承認時に決めてほしい点
1. 使い捨てクローンの場所と、実行してよいか
2. 実装担当の権限（上記の `--tools` 制限と `acceptEdits` でよいか）
3. `--max-budget-usd` の金額上限（付ける場合）
4. Codex の出力を `-o <file>` で受け取る方式にするか（現在は標準出力）

### 3.6 未検証の項目
- `claude -p` の `--permission-prompts none` と `--strict-mcp-config` のフラグが現在のバージョンで有効か
- `codex exec --output-schema` が想定どおり JSON を返すか
- 作業ディレクトリ外への書き込みを `acceptEdits` が防ぐか

これらは実行前に `claude --help` / `codex exec --help` で確認するが、実AIを呼ばずに確認できる範囲に限る。

## 4. 未解決事項
- `test_symlink_path_is_rejected` は、この環境では skip されることがある（開発者モードの有無で変わる可能性）。
- 前回の初回失敗（21件）が再現しなかった理由は不明。
- 実CLI結合テストは未実施。
