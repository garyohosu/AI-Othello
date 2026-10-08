# Result00003 — 汎用AI自動開発Controller（最小実用版）

対応する指示書: [Instruction00003.md](./Instruction00003.md)
実施日: 2026-10-08
実行担当: Claude Code（Claude Opus 5.5）
作業環境: Windows 11 Pro 10.0.26200 / Python 3.14.0（`py`）/ pytest 9.0.2 / PyYAML 6.0.3 / Git for Windows

## 0. 要約
- **完了。** 汎用コントローラ `tools/devloop/` を実装し、モックによる閉ループ（retry → complete の2ループ）と安全装置をテストで確認した。
- **実AI（Claude Code / Codex）の呼び出し: 0件。課金を伴う操作: 0件。** 本番の自動開発ループは指示どおり実施していない。
- pytest: **176 passed**（オセロ本体 120件 + devloop 56件）、失敗0、警告352件（すべて環境の `pytest_freezegun` プラグイン由来）。
- ただし、devloop テストの**初回実行だけ21件が失敗し、原因を特定できていない**（6.3節）。以後の7回の実行（a//b 修正前の2回を含む）では、この21件は一度も再現しなかった。
- コミット: 実装 `18431cd`（push 済み）。本ファイルは別コミットで push する（10節）。

## 1. 依存作業（Instruction00002）の状態
- `instructions/Result00002.md` は存在する（コミット `523e693`）。作業00002は Result00002 に記録したとおり完了している。
- 本作業は、オセロ本体のコード（`game.py`、`ai_runner.py`、`tournament.py`、`main.py`、`game_statistics.py`）を変更していない。devloop は独立ディレクトリ `tools/devloop/` に置き、オセロのモジュールを import しない。
- `main.py`（オセロ用CLI）とは別の入口 `py -m tools.devloop.controller` にした。

## 2. 実装した構成

| ファイル | 内容 |
|---|---|
| `tools/devloop/controller.py` | メイン制御（argparse）。dry-run 計画、実行ループ、機械的チェック、停止判定、再開 |
| `tools/devloop/adapters.py` | 実装担当・レビュー担当の起動層（mock / claude / codex）。引数リストで起動、タイムアウト・Ctrl+C 時にプロセスツリーごと終了、秘密情報のマスク |
| `tools/devloop/schema.py` | レビュー結果のJSON検証（厳密な型検証）と JSON Schema（strict 形式） |
| `tools/devloop/state.py` | `.devloop/state.json`（状態）と `.devloop/log.jsonl`（イベントログ） |
| `tools/devloop/safety.py` | パス検証（`..`・絶対パス・シンボリックリンク/ジャンクション拒否）、変更の分類（削除・保護対象）、テストコマンドの許可判定 |
| `tools/devloop/gitutil.py` | 読み取り専用の Git 操作（rev-parse / status / diff / ls-files のみ。それ以外は例外） |
| `tools/devloop/config.example.yaml` | 設定例（dry_run: true、allow_real_cli: false、実CLIのコマンドは未検証の例） |
| `tests/test_devloop.py` | モックによるテスト56件 |
| `tests/devloop_mocks/mock_implementer.py` / `mock_reviewer.py` | シナリオファイルに従って動くモック（AIは呼ばない） |
| `docs/devloop.md` | 利用方法・停止理由・安全上の制約 |
| `README.md` / `.gitignore` | devloop の節を追加 / `.devloop/` と `devloop.yaml` を除外 |

### 2.1 ループの流れ
1. 開始前: Git作業ツリーのルートか、指示書が `instructions/InstructionNNNNN.md`（5桁）か、テストコマンドが許可された実行ファイルか、作業ツリーがクリーンか（ユーザーの変更を上書きしないため）を確認する。
2. 実装担当を実行する。`ResultNNNNN.md` が既にあれば実行せずに停止する（上書きしない）。
3. 機械的チェック（コントローラ自身が実行）:
   - 結果報告: 存在する、UTF-8、空でない、Markdown の見出しがある、1MB以下、設定した必須項目を含む
   - Git: 実装担当がコミットしていないか（HEAD の変化）、ファイル削除・保護対象（依存関係・CI・秘密情報・tools/devloop）の変更がないか
   - テスト: 設定ファイルの `test_commands` を実行して終了コードを記録する
4. レビュー担当に、指示書・結果報告・差分・機械的チェックの結果を渡す。前後で作業ツリーのスナップショット（HEAD、status、差分、未追跡ファイルの内容）を比べ、変わっていたら停止する。
5. 出力全体が4項目（decision / summary / issues / next_instruction）だけのJSONオブジェクトでなければ停止する。
6. complete: テストが全て成功していれば完了。失敗していれば `inconsistent_review` で停止する。blocked: 停止する。retry: 同じ失敗の繰り返し・ループ上限を確認し、`Instruction(NNNNN+1).md` を新規作成（既存なら停止）して次のループへ進む。

### 2.2 安全装置
| 要件 | 実装 |
|---|---|
| 初期設定は dry-run | 既定は計画表示のみ。実行には設定 `dry_run: false` と `--execute` の両方が必要。dry-run は AI のプロセスを起動せず、`.devloop/` も作らない |
| 実AIは明示的な許可の後のみ | `provider: claude / codex` は設定 `allow_real_cli: true` と `--allow-real` の両方が必要。なければ `approval_required` で停止。実AIのCLI名（claude / codex / gemini / grok など）を `mock` として登録すると設定エラー |
| 最大3ループ・上限 | `max_loops` は1〜3（4以上は設定エラー）、`max_total_calls`（既定6）、`max_same_failure`（既定2）、役割ごとの `timeout_sec`、テストの `test_timeout_sec` |
| 技術エラーで停止 | タイムアウト・非ゼロ終了・起動失敗で `technical_error` |
| 自動push・merge・PR・commit・削除の禁止 | コントローラ自身はこれらを一切しない（Git は読み取りのみ）。実装担当のコミット・削除・保護対象の変更を検出したら停止 |
| 依存関係変更の禁止 | `requirements*.txt`、`pyproject.toml`、`package.json` などを保護対象にし、変更を検出したら停止 |
| 秘密情報 | ログ・状態ファイルの `sk-…`・`xai-…`・`AIza…`・`gh?_…`・`Bearer …` と、KEY/TOKEN/SECRET/PASSWORD を名前に含む環境変数の値をマスク |
| 信頼できない入力 | 指示書・結果報告・AI出力はデータとして扱い、そこに書かれたコマンドは実行しない。レビュー用プロンプトと自動生成の指示書にその旨を明記 |
| テストコマンドの境界 | 設定ファイルの `test_commands` だけを、`allowed_test_executables`（既定: py / python / python3 / pytest）の実行ファイルで、シェルなしで実行 |
| 書き込み範囲 | `instructions/` 直下の新規 `InstructionNNNNN.md`（`x` モードで作成）と `.devloop/` のみ。パストラバーサル・シンボリックリンク経由の書き込みを拒否 |
| 費用 | 金額上限は保証しない。呼び出し回数・所要時間・出力を記録する |

### 2.3 実CLIのコマンド例（未検証）
`config.example.yaml` の実CLIのコマンドは、Instruction00002 で取得した `--help` に記載のあるオプションだけで組んだ。**実際に動かしていない。**
- 実装担当（Claude Code 2.1.294）: `claude -p {prompt} --tools Read,Edit,Write,Glob,Grep --permission-mode acceptEdits --permission-prompts none --no-session-persistence --strict-mcp-config --disable-slash-commands`
  - Bash を含めないのでシェル実行はできない想定（テストはコントローラが実行する）。作業ディレクトリ外への書き込みが防がれるかは未確認。
- レビュー担当（Codex 0.161.0）: `codex exec -s read-only --ephemeral --skip-git-repo-check --color never --output-schema {schema_file} -`（プロンプトは標準入力）
  - `codex.cmd` は .cmd なので標準入力で渡す。最終回答だけが標準出力に出るかは未確認。

## 3. 実行したCLIコマンド（devloop 関連）
| コマンド | 結果 |
|---|---|
| `py -m tools.devloop.controller --repo . --instruction instructions/Instruction00003.md --config tools/devloop/config.example.yaml` | exit 0。計画のみ表示（下記）。`.devloop/` は作られなかった |
| 同上 + `--execute --allow-real` | exit 2。「設定が dry_run: true のため実行できない」。何も起動せず |

dry-run の出力:
```
[dry-run] AIのプロセスは起動せず、ファイルも書き込まない
リポジトリ: C:\PROJECT\AI-Othello
指示書: instructions/Instruction00003.md → 結果報告: instructions/Result00003.md
実装担当: provider=claude command=['claude', '-p', '{prompt}', '--tools', 'Read,Edit,Write,Glob,Grep', '--permission-mode', 'acceptEdits', '--permission-prompts', 'none', '--no-session-persistence', '--strict-mcp-config', '--disable-slash-commands'] timeout=1800.0s
レビュー担当: provider=codex command=['codex', 'exec', '-s', 'read-only', '--ephemeral', '--skip-git-repo-check', '--color', 'never', '--output-schema', '{schema_file}', '-'] timeout=600.0s
テストコマンド: [['C:\\Users\\hantani\\AppData\\Local\\Programs\\Python\\Python314\\python.exe', '-m', 'pytest', '-q']]
上限: ループ3回、AI呼び出し6回、同じ失敗2回で停止
次の指示書（retry 時）: instructions/Instruction00004.md
実AIの起動: 許可されていない（実行しても approval_required で停止する）
作業ツリー: 未コミットの変更あり → 実行時は停止する
```
（「未コミットの変更あり」は、実行時点で作業中の変更があったため）

claude / codex の実行ファイルは、この作業では `--help` / `--version` も含めて起動していない（Instruction00002 で取得済みのヘルプを参照した）。

## 4. 受け入れ基準との対応

| # | 基準 | 対応するテスト（`tests/test_devloop.py`） | 結果 |
|---|---|---|---|
| 1 | モックClaudeが結果を書き、モックCodexが retry → complete で2ループ終了 | `test_retry_then_complete_in_two_loops` | 成功（呼び出し4回、Instruction00002 を自動生成、コントローラはコミットしない） |
| 2 | blocked | `test_blocked_stops` | 成功 |
| 2 | 不正JSON（7パターン） | `test_invalid_review_stops[text/broken/prefixed/missing-key/bad-decision/retry-without-next/empty]` | 成功 |
| 2 | 結果ファイル欠落・不正 | `test_missing_result_stops_before_review`、`test_result_without_heading_or_required_section_stops`、`test_required_sections` | 成功 |
| 2 | テスト失敗 | `test_failed_tests_cannot_complete`（失敗のまま complete → 停止）、`test_failed_tests_then_fixed`（retry で修正 → 完了） | 成功 |
| 2 | CLIタイムアウト | `test_implementer_timeout`、`test_reviewer_timeout` | 成功 |
| 2 | 非ゼロ終了 | `test_nonzero_exit`、`test_reviewer_nonzero_exit` | 成功 |
| 2 | 最大3ループ到達 | `test_max_three_loops`（Instruction00004 は作らない）、`test_max_loops_configurable`、`test_max_loops_above_three_is_rejected` | 成功 |
| 2 | その他の停止 | `test_repeated_same_failure_stops`、`test_total_call_limit` | 成功 |
| 3 | 番号衝突で上書きしない | `test_next_instruction_number_conflict_does_not_overwrite`、`test_next_result_conflict`、`test_existing_result_is_not_overwritten`、`test_dirty_worktree_is_not_touched` | 成功 |
| 4 | テストコマンドを実際に走らせ終了コードを記録、実行許可の境界 | `test_retry_then_complete_in_two_loops`（exit_code 記録）、`test_failed_tests_cannot_complete`（exit_code 1）、`test_disallowed_test_commands`（git push / cmd / powershell / rm）、`test_allowed_test_command_resolves`、`test_disallowed_test_command_in_config_is_config_error` | 成功 |
| 5 | dry-run・モックで実AIを呼ばない | `test_dry_run_starts_no_process_and_writes_nothing`、`test_dry_run_is_default_in_cli`、`test_real_ai_requires_two_approvals`（プロセス起動を禁止した状態で確認）、`test_real_cli_cannot_be_registered_as_mock`、`test_example_config_is_safe` | 成功 |
| 6 | 既存のAI-Othelloテストの退行なし | `tests/test_game.py` 31件、`tests/test_runner.py` 51件、`tests/test_tournament.py` 38件 | 120件すべて成功 |
| 7 | 実績の記載 | 本ファイル6節 | — |

追加の安全装置のテスト: `test_implementer_commit_is_detected`、`test_file_deletion_is_detected`、`test_dependency_change_is_detected`、`test_reviewer_modification_is_detected`、`test_reviewer_editing_untracked_result_is_detected`、`test_unsafe_paths_are_rejected`（7パターン）、`test_symlink_path_is_rejected`、`test_instruction_name_rules`、`test_instruction_outside_instructions_dir_is_config_error`、`test_interrupt_and_resume`、`test_log_masks_secrets`、`test_review_schema`。

## 5. 設計上の判断
- **テスト失敗時の扱い**: テストが失敗してもすぐには止めず、レビュー担当に結果を渡して retry させる（修正の機会を与える）。ただし complete は受け付けず `inconsistent_review` で停止する。同じ指摘・同じテスト結果が2回続いたら `repeated_failure` で停止する。
- **作業ツリーがクリーンでないと開始しない**: ユーザーの未コミットの変更を上書き・混同しないため。2ループ目以降は1ループ目の変更が残った状態で続ける（コミットしないため）。差分は開始時の HEAD との比較でレビュー担当に渡す。
- **結果報告が既にあれば実装担当を起動しない**: 番号衝突として停止。ただし `--resume` で再開した場合は、中断前に実装担当が書き終えたものとみなしてチェックへ進む。
- **ファイル名の変更（git status の R）も削除として扱う**（`allow_delete: false` の場合）。

## 6. テスト

### 6.1 実行したコマンドと結果
| コマンド | 結果 |
|---|---|
| `py -m pytest -q tests/test_devloop.py`（初回） | **22 failed, 34 passed**（6.3節） |
| `py -m pytest -q -p no:freezegun tests/test_devloop.py::test_blocked_stops` | 1 passed |
| `py -m pytest -q -p no:freezegun -x tests/test_devloop.py` | `test_unsafe_paths_are_rejected[a//b]` で失敗（実装の不具合。6.2節） |
| `py -m pytest -q -p no:freezegun tests/test_devloop.py` | 1 failed（a//b）, 55 passed |
| `py -m pytest -q tests/test_devloop.py` | 1 failed（a//b）, 55 passed |
| （a//b を修正後）`py -m pytest -q tests/test_devloop.py` を3回 | 3回とも 56 passed |
| `__pycache__` を削除してから `py -m pytest -q tests/test_devloop.py` | 56 passed |
| `py -m pytest -q`（最終、全体） | **176 passed, 352 warnings in 91.96s** |

内訳: `tests/test_game.py` 31、`tests/test_runner.py` 51、`tests/test_tournament.py` 38、`tests/test_devloop.py` 56。

警告352件はすべて `site-packages\pytest_freezegun.py:17` の DeprecationWarning（distutils の LooseVersion）。本リポジトリのコード由来ではない。

### 6.2 修正した不具合
- `safe_repo_path` が `a//b`（空の要素を含むパス）を拒否していなかった。パスの分割が連続する区切り文字を1つにまとめていたため。区切り文字ごとに分割するよう直した。

### 6.3 原因不明の初回失敗（未解決）
- devloop テストの初回実行で22件が失敗した。1件は上記の a//b。残り21件は「complete / 期待した停止理由のはずが、別の理由で stopped になった」という失敗だった。
- 初回は停止理由（`reason` / `detail`）を assert メッセージに出していなかったため、**どの理由で止まったかを記録できておらず、原因は特定できていない。**
- その後、devloop テストを含む実行を7回行い（`__pycache__` を消した状態、全体実行を含む）、この21件の失敗は一度も再現しなかった。初回実行の所要時間（34秒）が以後（45〜50秒）より短かったことから、早い段階で停止していたと考えられる。新規ファイルの初回実行時のウイルス対策ソフトのスキャンなどの環境要因を疑っているが、裏付けはない。
- 対策として、テストの assert に `Outcome`（停止理由と詳細を含む）を出すようにした。再発したら停止理由が表示される。
- 本番運用の前に、別の環境（または新しいクローン）での初回実行で再現するかを確認することを推奨する。

### 6.4 未実施
- 実際の Claude Code / Codex を使った自動開発ループ（指示により今回は実施しない）。
- 実CLIのコマンド例の動作確認（権限制限が効くか、出力形式）。
- Linux / macOS での実行（プロセスグループの終了処理は POSIX 用のコードを書いたが未テスト）。

## 7. 変更ファイル
| ファイル | 変更 |
|---|---|
| `tools/__init__.py`、`tools/devloop/__init__.py` | 新規 |
| `tools/devloop/controller.py`、`adapters.py`、`schema.py`、`state.py`、`safety.py`、`gitutil.py` | 新規 |
| `tools/devloop/config.example.yaml` | 新規 |
| `tests/test_devloop.py`、`tests/devloop_mocks/mock_implementer.py`、`tests/devloop_mocks/mock_reviewer.py` | 新規 |
| `docs/devloop.md` | 新規 |
| `README.md` | devloop の節を追加 |
| `.gitignore` | `.devloop/`、`devloop.yaml` を追加 |

オセロ本体のコード・テスト・SPEC は変更していない。

## 8. 未解決事項
- 6.3節の初回失敗の原因。
- 実CLIでの動作（権限の制限、出力形式、Codex の `--output-schema` と標準出力の関係、Claude Code の作業ディレクトリ外への書き込み）。
- 費用の計測: 各CLIの使用量を取得する方法が未確認のため、金額の上限は保証できない。
- 実装担当が `.gitignore` 対象のファイルを変更した場合、Git の差分に出ないため検出できない（保護対象・削除の検出は Git の追跡対象のみ）。
- 実装担当のプロセスがリポジトリ外に書き込むことは、コントローラでは防げない（CLI側の権限制限に依存する）。

## 9. 次の作業候補と、本番テスト前に必要な判断
1. **本番テストの承認**: 実際の Claude Code（実装担当）と Codex（レビュー担当）でループを回すか。回す場合の推奨手順:
   - 使い捨てのリポジトリ（または新しいブランチのクローン）で、`max_loops: 1`、`max_total_calls: 2` から始める
   - 簡単な指示書（例: 1ファイルに関数を1つ追加してテストを書く）を使う
2. **実装担当の権限**: 例の `--tools Read,Edit,Write,Glob,Grep --permission-mode acceptEdits` でよいか。Claude Code の `--max-budget-usd`（ヘルプ記載、`--print` 時のみ）を付けるか。
3. **レビュー担当の構成**: Codex の `-s read-only` でよいか（読み取り系のコマンド実行はありうる）。標準出力ではなく `-o <file>` で最終回答を受け取る方式に変えるか。
4. 6.3節の初回失敗の再現確認。
5. AI-Othello 本体側の次の作業（Result00002 の9節: 実CLIでの疎通確認と、廉価モデル2種類での1局）は引き続き承認待ち。

## 10. コミット
- 実装: `18431cd` feat: add generic AI dev-loop controller (tools/devloop) with mock-tested safety（`main` に push 済み、`523e693..18431cd`）
- 本ファイル（Result00003.md）と dream.md は、この後の別コミットで push する。
- devloop コントローラ自身には push 権限を与えていない（コード上 Git は読み取り専用）。
