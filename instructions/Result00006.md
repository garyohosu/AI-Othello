# Result00006 — devloop のプロンプト受け渡しを標準入力（UTF-8 バイト列）に変更し、無課金の回帰テストを追加

対応する指示書: [Instruction00006.md](./Instruction00006.md)
引継ぎ: [Result00005.md](./Result00005.md)（コミット `f7b58c4`）
実施日: 2026-10-10
実行担当: Claude Code（Claude Haiku 5.5）
作業環境: Windows 11 Pro 10.0.26300 / Python 3.13（`py`）

## 0. 要約
- **完了。** Claude 実装担当の設定を標準入力方式に変更し、子プロセスへ届くプロンプトが UTF-8 のバイト列として完全一致することをテストで確認した。
- テストの過程で、**Windows では既存の実装が `\n` を `\r\n` に変換して送っていた**ことが分かったため、`adapters.py` の入出力をバイナリ化して修正した（§3）。
- テスト: devloop **62 passed**（前回56 → 追加6）、全体 **182 passed**。失敗0、skip 0。
- dry-run: 実AIを起動せず、`.devloop/` も作らず、終了コード0。
- **実AI呼び出し: 0回。** `claude -p` / `codex exec` は実行していない。この作業では CLI の `--help` / `--version` も実行していない（必要な情報は Result00005 で確認済み）。
- 未検証: 実 Claude CLI が標準入力のプロンプトを受け付けるか（§5）。

## 1. リポジトリの同期
- 開始時: `main` は `origin/main` より1コミット遅れ（`88f5436`: Instruction00006 の追加）。未コミットの変更はなし。
- `git pull --ff-only origin main` で同期した（履歴の書き換えなし）。
- 同期後、`instructions/Instruction00006.md` と先行する `Result00005.md` を確認した。既存の Instruction/Result は変更していない。

## 2. 変更内容

### 2.1 設定（`tools/devloop/config.example.yaml`）
- 実装担当（Claude）の `command` から `{prompt}` を取り除いた。
  - 変更前: `["claude", "-p", "{prompt}", "--tools", ...]`
  - 変更後: `["claude", "-p", "--tools", ...]`
- 権限関連の引数（`--tools Read,Edit,Write,Glob,Grep`、`--permission-mode acceptEdits`、`--permission-prompts none`、`--no-session-persistence`、`--strict-mcp-config`、`--disable-slash-commands`）は変更していない。
- コメントに「標準入力へ UTF-8 で送る」「Windows の引数長制限を避けるため」を追記した。
- `note` に「claude -p が標準入力からのプロンプトを受け付けるかは実CLIで未確認」と明記した。

### 2.2 ドキュメント（`docs/devloop.md`）
- プレースホルダの説明を分けて記載した。
  - プロンプトは既定で標準入力に UTF-8 で送る。`{prompt}` を入れた場合だけ引数で渡す。
  - 長文が引数の上限を超えるため、長文は標準入力を使う。
  - Claude 実CLIの標準入力対応は未検証。モックで確認したのは「子プロセスの標準入力に UTF-8 のプロンプトが完全一致で届くこと」だけ。
  - `.cmd` に `{prompt}` を使うと拒否する既存の規則は変えていない。

### 2.3 `tools/devloop/adapters.py`（必要性がテストで示されたため修正）
- 原因: `subprocess.Popen(..., encoding="utf-8")` のテキストモードでは、Windows の標準入力が `\n` を `\r\n` に変換する。その結果、子プロセスは UTF-8 のプロンプトを**バイト単位で変えられた状態**で受け取っていた。
- 修正:
  - `Popen` からテキストモード指定を外し、標準入出力をバイナリで扱う。
  - 送信は `stdin_text.encode("utf-8")` で行う。
  - 出力は新しい `_decode()`（UTF-8、`errors="replace"`、`None` は空文字）で復元する。
  - タイムアウトと例外の分岐も同じ経路で `_decode()` を使う。
- 変更規模: `adapters.py` の差分は17行。`resolve_argv()` の `.cmd/.bat` 拒否ロジックは変更していない。

### 2.4 テストのモック（`tests/devloop_mocks/mock_reviewer.py`）
- `--prompt-out` の書き出しを、テキストモードからバイナリ（UTF-8 の `encode`）へ変えた。テキストモードだと Windows で改行が `\r\n` に変わり、受け取った内容と比較できないため。
- 標準入力の読み込みは従来どおり `sys.stdin.buffer.read().decode("utf-8")`。

## 3. テストの追加（`tests/test_devloop.py`）
追加は6件。すべて実AIを使わず、既存のモック（`tests/devloop_mocks/`）または子プロセスの `python -c` を使う。

| テスト | 確認内容 |
|---|---|
| `test_prompt_reaches_child_stdin_byte_exact` | 日本語・改行・記号・タブ・絵文字（🎲♟）を含み、64KiB を超えるプロンプトが、子プロセスの標準入力に**バイト完全一致**で届くこと |
| `test_long_prompt_is_not_passed_in_argv_without_placeholder` | `{prompt}` がない場合、約600KBのプロンプトが argv に現れず、引数の最大長が小さいこと |
| `test_prompt_placeholder_still_passes_as_argument` | `{prompt}` がある場合は従来どおり引数で渡すこと |
| `test_prompt_argument_is_rejected_for_cmd_wrapper` | `.cmd` に `{prompt}` を渡すと `AdapterError` になること（既存の安全規則の退行防止） |
| `test_child_that_ignores_stdin_does_not_hang_or_crash` | 標準入力を読まずに終了する子プロセスに約600KBを送っても、例外にならず、タイムアウトもしないこと |
| `test_example_claude_command_sends_prompt_via_stdin` | 設定例の Claude コマンドが `claude -p` で始まり、`{prompt}` を含まないこと |

- 最初の `test_prompt_reaches_child_stdin_byte_exact` は、§2.3 の CRLF 変換により**失敗した**（`b'\r' != b'\n'`）。修正後に成功した。
- 既存の `test_real_ai_requires_two_approvals` / `test_example_config_is_safe` / `test_dry_run_*` も通過した。

## 4. 実測結果

| コマンド | 結果 |
|---|---|
| `py -m pytest -q tests/test_devloop.py -rs` | **62 passed**（36.01秒）、skip 0 |
| `py -m pytest -q` | **182 passed**（83.95秒）、失敗0、skip 0 |

- 前回（Result00005）の内訳は、devloop 56件 + オセロ本体 120件 = 176件。今回は devloop +6 で 182件。

### 4.1 dry-run
- コマンド: `py -m tools.devloop.controller --repo . --instruction instructions/Instruction00006.md --config tools/devloop/config.example.yaml --dry-run`
- 結果（抜粋）:
  - `[dry-run] AIのプロセスは起動せず、ファイルも書き込まない`
  - 実装担当: `claude -p --tools Read,Edit,Write,Glob,Grep ...`（`{prompt}` なし）
  - レビュー担当: `codex exec -s read-only ... --output-schema {schema_file} -`
  - 上限: ループ3回、AI呼び出し6回、同じ失敗2回で停止（設定例のとおり）
  - `実AIの起動: 許可されていない（実行しても approval_required で停止する）`
  - `作業ツリー: 未コミットの変更あり → 実行時は停止する`（この作業のコミット前の状態。コミット後は「クリーン」になる想定）
  - 終了コード 0
- 副作用: `.devloop/` は作られていない。

## 5. 未検証事項（実CLIでの確認が必要）
- `claude -p` が**標準入力からプロンプトを受け付けるか**。モックは子プロセスの標準入力契約を確認したにすぎず、Claude 本体の挙動は確認していない。
- 長文（約600KB）の標準入力が、実 Claude CLI で切り詰められずに処理されるか。
- `acceptEdits` が作業ディレクトリ外への書き込みを防ぐか。
- `--max-budget-usd` の実効性（Result00005 から変更なし）。
- Codex の金額上限は CLI に存在しない（Result00005 から変更なし）。

## 6. 実CLIを使う操作
- 本作業では実行していない。`allow_real_cli: true`、`--allow-real`、`--execute` の組み合わせは使っていない。
- 実CLIの結合テストは、Result00005 §3 の手順と§5 の承認事項に従い、ユーザーの明示的な承認が必要。

## 7. 次に必要な承認・判断
1. 使い捨てクローンで、Claude 1回・Codex 1回の最小結合テストを実際に実行してよいか（費用が発生し得る）。
2. Claude の `--max-budget-usd` を付けるか。付ける場合の金額。
3. Codex の費用をどの方法で管理するか（CLI に金額上限がないため）。
4. Codex の出力を標準出力で受けるか、`-o <file>` で受けるか（現状は標準出力）。
