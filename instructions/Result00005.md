# Result00005 — 実CLI結合テストの事前準備（実AI呼び出しなし）

対応する指示書: [Instruction00005.md](./Instruction00005.md)
実施日: 2026-10-10
実行担当: Claude Code（Claude Haiku 5.5）
作業環境: Windows 11 Pro 10.0.26300 / Python 3.13（`py`）/ Git for Windows
CLI: `claude` 2.1.295（`C:\Users\garyo\.local\bin\claude.exe`）/ `codex` codex-cli 0.153.0（`C:\Users\garyo\AppData\Roaming\npm\codex.cmd`）

## 0. 要約
- **完了。** 作業1〜5を実施した。
- **実AI呼び出し: 0回。** `claude -p`、`codex exec` は実行していない。CLI は `--version` / `--help` のみ。
- pytest（全体）: **176 passed**、失敗0、skip 0。devloop（`tests/test_devloop.py`）: **56 passed**、skip 0。
- dry-run（`max_loops: 1`、`max_total_calls: 2`、`max_same_failure: 1`）: 計画表示のみ、終了コード0、`.devloop/` は生成されず、作業ツリーは変更なし。
- 実CLI結合テストは**未実行**。承認待ち（§5）。

## 1. 作業1: Result00004 の保全・同期・push
- 開始時の状態: ローカル `main` は `1243b88` の上に `6773908`（モック修正）があり、`instructions/Result00004.md` は未追跡。`origin/main` は `525aefc`（Instruction00005 追加）が先に進んでいた。
- `instructions/Result00004.md` だけをコミットした（上書き・削除なし）。
- `git rebase origin/main` は競合なしで成功した。履歴書き換えに伴い、モック修正のコミットハッシュは `6773908` → `f34bd1b` に変わった（内容は同じ。リモートへの push 前だったため force push は不要）。
- 通常の `git push origin main` で `525aefc..f851ce3` を push した。
- 最終履歴:
  ```
  f851ce3 docs: add Result00004 (devloop mock UTF-8 fix and real CLI test plan)
  f34bd1b test: read mock stdin as UTF-8 bytes to fix Windows cp932 failures
  525aefc docs: add Instruction00005 for no-cost real CLI test preparation
  1243b88 docs: end-of-day work log
  ```
- `Instruction00005.md` は編集していない。`Instruction00004.md` は作成していない。

## 2. 作業2: CLI オプションの実在確認（`--version` / `--help` のみ）

### 2.1 Claude Code（`claude` 2.1.295）
`claude --help` で存在を確認したもの:
- `-p, --print`
- `--tools <tools...>`（例: `"Bash,Edit,Read"`。`""` で全無効、`"default"` で全部）
- `--permission-mode <mode>`（choices: `acceptEdits`, `auto`, `bypassPermissions`, `manual`, `dontAsk`, `plan`）
- `--permission-prompts <target>`（`--print` 時のみ。`host` または `none`。`none` は確認が必要な操作を自動拒否する）
- `--no-session-persistence`（`--print` 時のみ）
- `--strict-mcp-config`（`--mcp-config` のみを使う）
- `--disable-slash-commands`（Skills を無効化）
- `--max-budget-usd <amount>`（`--print` 時のみ、API 呼び出しの上限）
- `--json-schema <schema>`、`--output-format`、`--model`、`--allowedTools` / `--disallowedTools`

**ヘルプの記載と実動作の区別:** 上記はヘルプに載っていることだけを確認した。`acceptEdits` が作業ディレクトリ外への書き込みを防ぐか、`--max-budget-usd` が実際に上限として効くかは、実AIを呼ばないと確認できない（未検証）。

### 2.2 Codex（codex-cli 0.153.0）
`codex exec --help` で存在を確認したもの:
- `-s, --sandbox <SANDBOX_MODE>`（`read-only`, `workspace-write`, `danger-full-access`）
- `--ephemeral`、`--skip-git-repo-check`、`--color <always|never|auto>`
- `--output-schema <FILE>`（最終応答の JSON Schema）
- `-o, --output-last-message <FILE>`（最終メッセージをファイルに書く。標準出力を使わない方式の候補）
- `--json`（イベントを JSONL で標準出力に出す）
- `[PROMPT]` を `-` にすると標準入力から読む（ヘルプ記載）
- `-C, --cd <DIR>`、`--add-dir <DIR>`

**金額上限:** `codex exec --help` の全文に対して `budget` / `cost` / `limit` / `token` を検索したが、該当オプションはなかった。**Codex には金額上限を指定するオプションが存在しない。** Codex 側の費用は上限を強制できないと記録する。

### 2.3 config.example.yaml との照合
- 上記の Claude フラグ（`-p`、`--tools`、`--permission-mode`、`--permission-prompts none`、`--no-session-persistence`、`--strict-mcp-config`、`--disable-slash-commands`）はすべてヘルプに存在し、構文も一致した。
- Codex のフラグ（`exec`、`-s read-only`、`--ephemeral`、`--skip-git-repo-check`、`--color never`、`--output-schema`、`-`）もすべて存在し、一致した。
- 矛盾がなかったため、設定例とドキュメントは**変更していない**。
- 認証情報・トークンは表示していない。

### 2.4 残るリスク（未検証）
- **Windows のコマンドライン長:** `claude` の実装担当は `{prompt}` を argv で渡している。Windows の引数長には上限があり（約32KB）、長い指示書では起動に失敗するおそれがある。stdin 渡し（`{prompt}` を外す）への変更を検討する余地がある。`claude -p` が stdin からの入力を受け付けるかは未確認。
- **`codex` は .cmd（npm 製）:** `adapters.py` は `.cmd/.bat` への `{prompt}` 引数渡しを拒否する。現在の codex 設定は標準入力（`-`）を使うため、この制限には当たらない。

## 3. 作業3: 安全な最小結合テストの計画（未実行）

### 3.1 実行環境
- 使い捨ての別クローン（例: `C:\project\AI-Othello-devloop-trial`）に新しいブランチ `devloop-trial` を切る。元のリポジトリは変更しない。
- クローンには `.devloop/`、`devloop.yaml`、秘密情報、未追跡ファイルをコピーしない。
- 作業後はクローンを削除する。

### 3.2 設定（最初の1回）
```yaml
dry_run: false          # --execute のときだけ有効
allow_real_cli: true    # --allow-real のときだけ有効
max_loops: 1
max_total_calls: 2      # Claude 1回 + Codex 1回
max_same_failure: 1
require_clean_worktree: true
allow_delete: false
```
- 実装担当（Claude）: `--tools Read,Edit,Write,Glob,Grep`、`--permission-mode acceptEdits`、`--permission-prompts none`、`--no-session-persistence`、`--strict-mcp-config`、`--disable-slash-commands`。Bash は含めない。
- 費用: `--max-budget-usd 1` を付けるかは承認事項（§5）。付けても Codex の費用は含まれない。
- レビュー担当（Codex）: `-s read-only --ephemeral --skip-git-repo-check --color never --output-schema {schema_file} -`。

### 3.3 課題
- 小さな課題のみ（例: 既存モジュールに関数を1つ追加し、そのテストを1つ書く）。
- 禁止: 依存関係の変更、ファイル削除、外部への送信、`git push`、CI・秘密情報ファイルの変更。
- 指示書は `instructions/Instruction00001.md` の形式（5桁番号）に合わせる。ただし試験用であり、このリポジトリにはコミットしない。

### 3.4 手順
1. クローンを作り、devloop が動く状態か `py -m pytest -q tests/test_devloop.py` で確認する（実AIなし）。
2. 試験用の設定で `--dry-run` を実行し、表示されたコマンドラインを目視で確認する。
3. 承認を得てから `--execute --allow-real` で1回だけ実行する。
4. 完了後に `.devloop/log.jsonl`、`git status`、`git diff` を確認し、結果を `Result` に記録する。
5. 想定外の変更があれば、その時点でクローンを破棄する。

### 3.5 停止条件
- 機械的チェックの失敗、同じ失敗の繰り返し、タイムアウト（実装 1800秒、レビュー 600秒）、保護対象パスの変更、CLI の異常終了、権限拒否のいずれか。

### 3.6 費用の注意
- Claude Code の `--max-budget-usd` は API 呼び出しの上限として記載されているが、実動作は未確認。
- Codex には金額上限がない。Codex の費用はサブスクリプション枠か従量課金かを、実行前に利用アカウントで確認する必要がある（この作業では確認していない）。
- したがって「総額1ドル以内」は保証できない。

## 4. 作業4: 課金なしの検証

### 4.1 pytest
| コマンド | 結果 |
|---|---|
| `py -m pytest -q`（全体） | 176 passed（73.76秒）、失敗0、skip 0 |
| `py -m pytest -q tests/test_devloop.py -rs` | 56 passed（35.73秒）、skip 0 |

- 前回報告の「55 passed, 1 skipped」（symlink テストが skip）は、今回の実行では再現しなかった。skip 条件（`os.symlink` の権限）の違いと思われるが、環境の差を確認していない。管理者権限や開発者モードの変更は行っていない。

### 4.2 dry-run
- 試験用設定: `%TEMP%\claude\...\scratchpad\devloop-dryrun.yaml`（リポジトリの外。`dry_run: true`、`allow_real_cli: false`、`max_loops: 1`、`max_total_calls: 2`、`max_same_failure: 1`）。
- コマンド: `py -m tools.devloop.controller --repo . --config <上記> --instruction instructions/Instruction00005.md --dry-run`
- 結果（抜粋）:
  - `AIのプロセスは起動せず、ファイルも書き込まない`
  - 計画: 実装担当 `claude`、レビュー担当 `codex`、テスト `python -m pytest -q`
  - `実AIの起動: 許可されていない（実行しても approval_required で停止する）`
  - `作業ツリー: クリーン`
  - 終了コード 0
- 副作用の確認: `.devloop/` は作られていない。`git status` の変更なし。

### 4.3 設定ファイルの変更
- `tools/devloop/config.example.yaml`、`docs/devloop.md` は変更していない（§2.3 のとおり矛盾がなかった）。
- `tools/devloop/` 本体は変更していない。

## 5. 承認が必要な事項（次の作業の前に）
1. 使い捨てクローンで、§3 の最小結合テストを**実AIを呼んで**実行してよいか（Claude 1回、Codex 1回。費用が発生し得る）。
2. Claude に `--max-budget-usd` を付けるか。付ける場合の金額。
3. Codex の費用をどの方法で管理するか（金額上限がないため、利用アカウント側の確認が必要）。
4. 実装担当の `{prompt}` を argv で渡す方式のままにするか（Windows の引数長制限の懸念。stdin 方式に変えるか）。
5. レビュー担当の出力を標準出力で受けるか、`-o <file>` で受けるか。

## 6. 未解決事項
- `acceptEdits` が作業ディレクトリ外への書き込みを防ぐかは未検証。
- `--max-budget-usd` の実効性は未検証。
- Codex の金額上限は存在しない。
- Windows の引数長制限（`{prompt}` の argv 渡し）は未検証。
- 前回の初回失敗（21件）の再現条件は不明のまま。
- symlink テストの skip の有無は環境依存（今回は skip なし）。
