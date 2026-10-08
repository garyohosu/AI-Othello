# devloop — 汎用AI自動開発ループ（最小実用版）

`tools/devloop/` は、Python から実装担当AI（Claude Code CLI を想定）と独立レビュー担当AI（Codex CLI を想定）を順に起動し、次のループを回すコントローラです。AI-Othello のコードには依存しないため、`--repo` で別のリポジトリにも使えます。

```
指示書 InstructionNNNNN.md
  → 実装担当が作業し ResultNNNNN.md を書く
  → コントローラが機械的にチェック（結果報告の存在と構造、Git差分、テストの終了コード）
  → レビュー担当が complete / retry / blocked を厳密なJSONで返す
  → retry なら Instruction(NNNNN+1).md を作って次のループへ（最大3ループ）
```

**現状（2026-10-08）: モックでの閉ループと安全装置をテスト済み。実際の Claude Code / Codex を使ったループは一度も実行していない。** 実CLIのコマンド例は `--help` で確認したオプションだけで組んだ未検証のもの。

## 使い方

```powershell
# 1. 設定をコピー（devloop.yaml は .gitignore 済み）
copy tools\devloop\config.example.yaml devloop.yaml

# 2. 計画の確認（既定。AIのプロセスは起動せず、ファイルも書かない）
py -m tools.devloop.controller --repo . --instruction instructions/Instruction00004.md

# 3. 実行（設定で dry_run: false にしたうえで --execute）
py -m tools.devloop.controller --repo . --instruction instructions/Instruction00004.md --execute

# 4. 実AIを使う実行（設定の allow_real_cli: true と --allow-real の両方が必要）
py -m tools.devloop.controller --repo . --instruction instructions/Instruction00004.md --execute --allow-real

# Ctrl+C で止めた実行の再開
py -m tools.devloop.controller --repo . --execute --resume
```

別のリポジトリに使う場合は `--repo <そのルート>` と `--config <設定ファイル>` を指定します。

### 終了コード
| コード | 意味 |
|---|---|
| 0 | complete、または dry-run |
| 2 | 設定エラー（dry_run: true のまま --execute した場合を含む） |
| 3 | 安全に停止（blocked、上限到達、承認が必要、検証失敗など） |
| 130 | Ctrl+C で中断（`--resume` で再開できる） |

### 停止理由（`.devloop/state.json` の `reason`）
| reason | 意味 |
|---|---|
| `complete` | レビュー担当が complete と判定し、テストも全て成功 |
| `blocked` | レビュー担当が blocked と判定（人間の判断が必要） |
| `approval_required` | 実AIの起動が許可されていない |
| `dirty_worktree` | 開始時に未コミットの変更がある（ユーザーの変更を上書きしないため） |
| `number_conflict` | 結果報告や次の指示書のファイルが既にある（上書きしない） |
| `technical_error` | タイムアウト、非ゼロ終了、起動失敗 |
| `result_missing` / `result_invalid` | 結果報告がない、空、見出しがない、必須項目がない |
| `forbidden_change` | 実装担当のコミット、ファイル削除、保護対象（依存関係・CI・秘密情報など）の変更 |
| `reviewer_modified_repo` | レビュー担当が作業ツリーを変更した |
| `invalid_review` | レビュー結果が規定のJSONではない |
| `inconsistent_review` | テストが失敗しているのに complete と判定された |
| `repeated_failure` | 同じ指摘・同じテスト結果が続いた（既定2回） |
| `max_loops` / `max_calls` | ループ上限（既定3、最大3）/ AI呼び出し回数の上限（既定6） |

## 安全上の制約
- **既定は dry-run。** 実行には「設定の `dry_run: false`」と「`--execute`」の両方が必要。dry-run では AI のプロセスを起動せず、`.devloop/` も作らない。
- **実AIは二重の許可制。** `provider: claude / codex` は「設定の `allow_real_cli: true`」と「`--allow-real`」の両方がないと起動しない。実AIのCLI（claude / codex / gemini / grok など）を `provider: mock` として登録すると設定エラー。
- **コントローラは commit / push / merge / PR作成 / ファイル削除をしない。** Git は `rev-parse` / `status` / `diff` / `ls-files` の読み取りだけを使う。
- 実装担当がコミットした、ファイルを削除した、保護対象のファイルを変えた場合は停止して人間に差分の確認を求める。
- レビュー担当の実行前後で作業ツリー（HEAD、status、差分、未追跡ファイルの内容）を比較し、変わっていたら停止する。
- **AIの「テスト済み」という文章では成功と判定しない。** 設定ファイルの `test_commands` をコントローラ自身が実行し、終了コードを記録してレビュー担当に渡す。テストが失敗していれば complete を受け付けない。
- テストコマンドは設定ファイルに書いたものだけを、`allowed_test_executables`（既定: py / python / python3 / pytest）の実行ファイルで、シェルを使わずに実行する。指示書やAIの出力に書かれたコマンドは実行しない。
- 指示書・結果報告・AIの出力は信頼できない入力として扱う。自動生成する指示書には、その旨と安全上の制約を明記する。
- 書き込み先は `instructions/` 直下の `InstructionNNNNN.md`（新規作成のみ、`x` モード）と `.devloop/` だけ。絶対パス、`..`、シンボリックリンク・ジャンクション経由のパスは拒否する。
- 上限: ループ数（1〜3）、AI呼び出し回数、同じ失敗の繰り返し、各プロセスのタイムアウト。タイムアウトや Ctrl+C ではプロセスツリーごと終了させる。
- 費用: 各CLIの使用量を正確に測れないため、金額の上限は保証しない。記録するのは呼び出し回数、所要時間、出力（秘密情報らしき文字列はマスク）。
- APIキー・トークンを設定やログに書かない。ログに出る `sk-…` などはマスクする。

## 設定項目
`tools/devloop/config.example.yaml` を参照。主な項目:

| 項目 | 既定 | 内容 |
|---|---|---|
| `dry_run` | true | false にしないと実行できない |
| `allow_real_cli` | false | 実AIの起動許可（`--allow-real` も必要） |
| `max_loops` | 3 | 1〜3 |
| `max_total_calls` | 6 | 実装担当とレビュー担当の呼び出し回数の合計 |
| `max_same_failure` | 2 | 同じ失敗が続いたら停止 |
| `test_commands` | （必須） | 引数配列のリスト |
| `allowed_test_executables` | py, python, python3, pytest | テストコマンドに使える実行ファイル |
| `protected_paths` | 依存関係・CI・秘密情報・tools/devloop | 変更を検出したら停止するパス（glob） |
| `allow_delete` | false | ファイル削除を許可するか |
| `require_clean_worktree` | true | 開始時に未コミットの変更があれば停止 |
| `result_required_sections` | [] | 結果報告に必要な文字列 |
| `implementer` / `reviewer` | | `provider`（mock / claude / codex）、`command`、`timeout_sec` |

`command` のプレースホルダ: `{python}` `{prompt}` `{instruction}` `{result}` `{repo}` `{schema_file}` `{model}`。`{prompt}` がなければプロンプトは標準入力で渡します。npm 製の `.cmd`（codex / gemini）に `{prompt}` を使うと、cmd.exe の引数解釈で壊れるおそれがあるため拒否します。

## レビュー結果のJSON
出力全体（前後の空白を除く）が次の4項目だけを持つJSONオブジェクトであること。説明文やコードブロックが付いていたら `invalid_review` で停止します。
```json
{"decision": "retry", "summary": "要約", "issues": ["指摘"], "next_instruction": "次の作業"}
```
`decision` は `complete` / `retry` / `blocked`。`retry` では `next_instruction` が必須。JSON Schema は実行時に `.devloop/review_schema.json` に書き出され、`{schema_file}` で CLI に渡せます（Codex の `--output-schema` を想定。未検証）。

## 実CLIでの本番テスト前に決めること
- 実装担当（Claude Code）の権限: 例では `--tools "Read,Edit,Write,Glob,Grep"` と `--permission-mode acceptEdits` を使う（シェル実行なし）。作業ディレクトリ外への書き込みが防がれるかは未検証。
- レビュー担当（Codex）: `-s read-only` は書き込みを制限するだけで、読み取り系のコマンド実行はありうる。最終回答だけが標準出力に出るかは未確認。
- モデル、1回あたりの費用の目安、`max_total_calls` の値。
- 最初の本番テストは、使い捨てのリポジトリで `max_loops: 1` から始めることを推奨する。
