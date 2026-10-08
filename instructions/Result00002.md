# Result00002 — 実AI CLI接続の準備（課金なし）

対応する指示書: [Instruction00002.md](./Instruction00002.md)
実施日: 2026-10-08
実行担当: Claude Code（Claude Opus 5.5）
作業環境: Windows 11 Pro 10.0.26200 / Python 3.14.0（`py` ランチャー）/ pytest 9.0.2 / PyYAML 6.0.3

## 0. 要約
- 指示書の作業1〜8はすべて完了した（未完了の作業はない。ただし実CLIの実動作は禁止事項のため未確認）。
- **実AIモデルへの問い合わせ: 0件。課金を伴う操作: 0件。** 実CLIに対して実行したのは `where`、`--version`、`--help`（`codex exec --help`、`grok agent --help` を含む）だけ。
- `statistics.py` を `game_statistics.py` に改名し、標準ライブラリ `statistics` を通常どおり import できることをテストで確認した。
- 4つのCLI（Claude Code / Codex / Gemini / Grok）を確認し、ヘルプで確認できたオプションだけで設定例を作った。すべて `enabled: false` にしてあり、モデルIDは「未確認」のままにした。
- pytest: **120 passed**（失敗0、警告240件。警告はすべて環境の `pytest_freezegun` プラグイン由来）。
- コミット: 実装 `91ba338`（push 済み）。本ファイルは別コミットで push する（9節）。

## 1. 作業ごとの完了状況

| # | 作業 | 状況 |
|---|---|---|
| 1 | 現状確認（pytest 再実行） | 完了。作業前の実行で 108 passed |
| 2 | 名前衝突解消 | 完了。`game_statistics.py` に改名、import・SPEC・README を更新、標準 `statistics` の import テストを追加 |
| 3 | CLI調査（モデル呼び出し禁止） | 完了。2節 |
| 4 | モデル設定 | 完了。`config/models.example.yaml` を更新、ローカル用 `config/models.yaml` を作成（Git 管理外であることを `git check-ignore` で確認） |
| 5 | セキュリティ | 完了。4節。既存のサンドボックス挙動は緩めていない（むしろ `validate --live` を厳しくした） |
| 6 | PermissionError 対策の確認 | 完了。原因は未確定。リトライ時のログを追加した。5節 |
| 7 | テスト | 完了。6節 |
| 8 | ドキュメント | 完了。README・SPEC を更新 |

## 2. CLI調査の結果

### 2.1 実行したコマンド
すべて `C:\Users\hantani\AppData\Local\Temp\claude\...\scratchpad\cli` で実行。Claude Code には自動更新を避けるため `DISABLE_AUTOUPDATER=1` と `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` を付けた（この環境変数の効果自体は検証していない）。

```
where.exe claude / codex / gemini / grok
claude --version / codex --version / gemini --version / grok --version
claude --help / codex --help / codex exec --help / gemini --help / grok --help / grok agent --help
```
`grok models` は「利用可能なモデルを表示」だが、通信や認証を伴う可能性があるため実行していない。CLIのインストール・更新はしていない。

### 2.2 CLIの所在とバージョン

| CLI | 実体 | バージョン |
|---|---|---|
| Claude Code | `C:\Users\hantani\.local\bin\claude.exe` | 2.1.294 (Claude Code) |
| Codex | `C:\Users\hantani\AppData\Roaming\npm\codex.cmd`（npm） | codex-cli 0.161.0 |
| Gemini | `C:\Users\hantani\AppData\Roaming\npm\gemini.cmd`（npm） | 0.50.0 |
| Grok Build | `C:\Users\hantani\.grok\bin\grok.exe` | grok 0.2.112 (9bbd559437) [stable] |

### 2.3 ヘルプで確認できたオプション
「確認」はヘルプに記載があったという意味であり、実際の動作は確かめていない。

**Claude Code 2.1.294**
| 観点 | オプション（ヘルプ記載） |
|---|---|
| 非対話実行 | `-p, --print`（Print response and exit） |
| モデル指定 | `--model <model>`（別名 `fable` / `opus` / `sonnet` または正式名） |
| プロンプト入力 | 位置引数 `prompt`。`-p` 時に標準入力を読むかは明記なし（「useful for pipes」とだけある） |
| 出力形式 | `--output-format text|json|stream-json`（`--print` 時のみ）、`--json-schema` |
| ツール制限 | `--tools ""`（組み込みツールをすべて無効）、`--allowedTools` / `--disallowedTools`、`--restricted`（コマンド実行系ツールを除去）、`--permission-mode`、`--permission-prompts none` |
| その他 | `--no-session-persistence`、`--strict-mcp-config`、`--disable-slash-commands`、`--safe-mode`、`--bare`、`--max-budget-usd <amount>`（`--print` 時のみ） |
| タイムアウト | なし |

**Codex CLI 0.161.0**
| 観点 | オプション（ヘルプ記載） |
|---|---|
| 非対話実行 | `codex exec` |
| モデル指定 | `-m, --model <MODEL>` |
| プロンプト入力 | 引数を省略するか `-` を指定すると標準入力から読む（明記あり） |
| 出力形式 | `--json`（JSONLイベント）、`-o, --output-last-message <FILE>`、`--output-schema <FILE>`、`--color never` |
| ツール制限 | `-s, --sandbox read-only|workspace-write|danger-full-access`（「モデルが生成したシェルコマンドを実行するときの」サンドボックス）。シェル実行そのものを無効にするオプションは見当たらない |
| その他 | `--ephemeral`、`--skip-git-repo-check`、`--ignore-user-config`、`--ignore-rules`、`-C, --cd <DIR>` |
| タイムアウト | なし |

**Gemini CLI 0.50.0**
| 観点 | オプション（ヘルプ記載） |
|---|---|
| 非対話実行 | `-p, --prompt`（ヘッドレス。「標準入力の内容の後ろに追加される」） |
| モデル指定 | `-m, --model` |
| 出力形式 | `-o, --output-format text|json|stream-json` |
| ツール制限 | `--approval-mode default|auto_edit|yolo|plan`（plan = read-only mode）、`-s, --sandbox`、`--policy`（ポリシーエンジン）、`--allowed-tools` は非推奨 |
| タイムアウト | なし |

**Grok Build CLI 0.2.112**
| 観点 | オプション（ヘルプ記載） |
|---|---|
| 非対話実行 | `-p, --single <PROMPT>`（1ターンで標準出力に出して終了）、`--prompt-file <PATH>`、`grok agent stdio/headless` |
| モデル指定 | `-m, --model <MODEL>` |
| 出力形式 | `--output-format plain|json|streaming-json`、`--json-schema` |
| ツール制限 | `--tools <TOOLS>`（許可リスト）、`--disallowed-tools`、`--deny`、`--disable-web-search`、`--no-subagents`、`--no-memory`、`--max-turns <N>`、`--sandbox <PROFILE>`、`--permission-mode` |
| タイムアウト | なし |

## 3. モデル設定（`config/models.example.yaml`）
- 既存のモック2件（有効）に加え、実CLIの設定例4件を追加した。4件とも `enabled: false`。
- `model` は全件 `"<未確認: 廉価モデルID>"` のプレースホルダ。廉価モデル候補の実際のIDは確認していない。
- プロンプトの渡し方は CLI の実体で選んだ。
  - `claude.exe` / `grok.exe`: `{prompt}` で引数として渡す（ヘルプに位置引数・`-p <PROMPT>` の記載あり）
  - `codex.cmd` / `gemini.cmd`: 標準入力で渡す（.cmd に引数で渡すと cmd.exe の解釈で壊れるおそれがあるため、アダプタ側で拒否するようにした）
- 出力はすべて `output: text`。JSON 出力のフィールド名はヘルプに記載がなく未確認なので、推測で `json_field` を書かなかった。
- ローカル用 `config/models.yaml` はサンプルのコピーとして作成した（認証情報なし、`.gitignore` 対象）。
- `py main.py validate` の実行結果（実CLIには `--version` のみ実行）:
```
設定OK: モデル6件、反則上限10、技術リトライ上限3
OK mock-first: ...python.exe version=未取得 prompt_via=stdin sandbox=restricted
OK mock-json: ...python.exe version=未取得 prompt_via=stdin sandbox=restricted
OK claude-cheap（無効）: C:\Users\hantani\.local\bin\claude.EXE version=2.1.294 (Claude Code) prompt_via=arg sandbox=unknown
OK codex-cheap（無効）: C:\Users\hantani\AppData\Roaming\npm\codex.CMD version=codex-cli 0.161.0 prompt_via=stdin sandbox=unrestricted
OK gemini-cheap（無効）: C:\Users\hantani\AppData\Roaming\npm\gemini.CMD version=0.50.0 prompt_via=stdin sandbox=unknown
OK grok-cheap（無効）: C:\Users\hantani\.grok\bin\grok.EXE version=grok 0.2.112 (9bbd559437) [stable] prompt_via=arg sandbox=unknown
exit=0
```

### 3.1 アダプタの変更（`ai_runner.py`）
- `{prompt}`（引数渡し）と `{prompt_file}`（作業ディレクトリの `prompt.txt` を渡す）のプレースホルダを追加。どちらもなければ従来どおり標準入力。両方の同時指定は設定エラー。
- `.cmd` / `.bat` の CLI に `{prompt}` を使う設定は、起動前に拒否して技術エラー（`launch`）にする。
- 試行ログに `prompt_via`（`stdin` / `arg` / `file`）を記録する。
- モデルごとの `env`（追加の環境変数）を追加。名前に KEY / TOKEN / SECRET / PASSWORD を含むものは設定エラー。

## 4. セキュリティ（任意コード実行・ファイル編集の抑止）
- 既存の方針を維持: `sandbox: restricted` 以外の実CLIは大会に参加できない。
- 判定（ヘルプ記載のみに基づく。どれも実動作は未検証なので `restricted` にはしていない）:

| CLI | 抑止に使えそうなオプション | 判定 | 理由 |
|---|---|---|---|
| Claude Code | `--tools ""`、`--restricted`、`--strict-mcp-config` | unknown | ヘルプ上は全ツール無効化が可能。実際に無効になるか未検証 |
| Codex | `-s read-only` | **unrestricted（除外）** | read-only は書き込み制限のみ。シェルコマンド実行を止めるオプションがない |
| Gemini | `--approval-mode plan`、`--policy` | unknown | plan は読み取り専用モード。シェル実行が止まるか未検証 |
| Grok | `--tools`、`--disallowed-tools`、`--sandbox <PROFILE>` | unknown | `--tools ""` の意味、プロファイル名が未確認 |

- 変更点:
  - `validate --live` は、`restricted` 以外の実CLIがあると `--allow-unrestricted` なしでは実行しないようにした（前回までは確認なしで呼べた）。実行時は空の作業ディレクトリ（`games/_validate/<日時>/`）を使う。
  - 実CLIのモデルを指定した `play` / `tournament` が実行前に拒否されることを、実際のコマンドで確認した（実CLIは呼んでいない）:
```
> py main.py play --black claude-cheap --white mock-first
サンドボックス制限を確認できていないモデル: claude-cheap
検証目的で動かす場合のみ --allow-unrestricted を付ける（実大会では使えない）
exit=2
> py main.py tournament --models codex-cheap,mock-first
サンドボックス制限を確認できていないモデルは大会に参加できない: codex-cheap
exit=2
```

## 5. Windows PermissionError の調査
- Result00001 の情報: 全体実行の1回で `test_resume_keeps_foul_count` が PermissionError で失敗した。トレースバックは保存されていない。
- 再現を試みた: リトライなしの `os.replace`（一時ファイル書き込み → fsync → 置換）を同じ TEMP 配下で5000回連続実行 → **PermissionError 0件**（14.5秒）。この作業中に全体テストを5回（ほかに部分実行あり）実行し、PermissionError は一度も出なかった。
- 結論: **原因未確定**。ウイルス対策ソフトや検索インデクサによる一時的なファイルのロックと推定しているが、裏付けはない。
- 既存の対策の確認と変更:
  - 対象は `PermissionError` のみ（他の例外はリトライしない。テストあり）。
  - 上限10回、待機は 0.05秒 × 試行回数（合計約2.25秒）。定数 `REPLACE_ATTEMPTS` / `REPLACE_WAIT_SEC` にした。
  - 原子的更新との整合性: 置換に失敗しても置換先は元の内容のまま残る。state.json の置換に失敗した場合は、追記済みのログ1行が未確定として再開時に切り捨てられることをテストで確認した。
  - **追加**: リトライのたびに、操作・置換元/置換先のパス・試行回数・例外の種類・errno・winerror を `games/_logs/ai-othello.log` に記録する（ファイルの内容や秘密情報は書かない）。リトライ後に成功した場合と、上限で諦めた場合（ERROR）も記録する。
  - 再発したら、このログで「どのファイルの、何回目で、どの winerror か」を追える。

## 6. テスト

### 6.1 実行したコマンドと結果
| タイミング | コマンド | 結果 |
|---|---|---|
| 作業前 | `py -m pytest -q` | 108 passed, 216 warnings |
| 改名・アダプタ変更後 | `py -m pytest -q tests/test_runner.py` | 46 passed |
| テスト追加後 | `py -m pytest -q` | 1 failed, 119 passed（下記） |
| テスト修正後 | `py -m pytest -q` | 120 passed |
| 設定例の変更後 | `py -m pytest -q` | 1 error（テストファイルの構文エラー。下記） |
| 修正後（最終） | `py -m pytest -q` | **120 passed, 240 warnings** |
| 退行確認 | `py -m pytest -q -k "tenth_foul or foul_count_is_not_reset or full_game_with_mock_cli or tournament_csv or interrupt_and_resume or tournament_interrupt or retry_aborted or stdlib_statistics"` | 8 passed |

- 1 failed: `test_main_refuses_real_cli_without_confirmation` が「`games/` が作られていない」ことを確認していたが、運用ログ用に `games/_logs/` が作られるようになったため失敗した。対局データが作られていないことを確認する形に直した（実装の不具合ではない）。
- 1 error: テスト修正用スクリプトをシェルのヒアドキュメント経由で書いた際に `\n` が実際の改行になり、テストファイルが構文エラーになった。Edit で直した。
- 警告240件はすべて `site-packages\pytest_freezegun.py:17` の DeprecationWarning（distutils の LooseVersion）。本リポジトリのコード由来ではない。

### 6.2 追加したテスト（12件）
- 標準ライブラリ `statistics` が import でき、リポジトリ内に `statistics.py` がないこと
- `prompt_via` の判定、`{prompt_file}` と `{prompt}` での実行（モックCLI）、`.cmd` への `{prompt}` の拒否（Windows のみ）
- `env` の受け渡しと、認証情報らしき名前の拒否
- ファイル置換: 2回失敗後に成功してログが残る、10回失敗で諦めて置換先が元のまま、PermissionError 以外はリトライしない、state.json の置換失敗後も再開できる
- 試行ログの `prompt_via`、運用ログファイルへの書き込み
- サンプル設定: 実CLIはすべて無効・`restricted` なし・モデルIDは未確認・プロンプトの渡し方が CLI の実体に合っている

### 6.3 未実施
- 実CLIを呼ぶテスト（`real_cli` マーカー）: 作成も実行もしていない。
- **実AI接続は「動作確認済み」ではない。** ヘルプを読んだだけ。

## 7. 変更ファイル
| ファイル | 変更 |
|---|---|
| `statistics.py` → `game_statistics.py` | 改名 |
| `main.py` | import 変更、運用ログ設定、validate の SKIP 表示・`--live` の制限強化 |
| `ai_runner.py` | プロンプトの渡し方、`env`、`.cmd` への引数渡しの拒否 |
| `tournament.py` | `replace_with_retry` のログ・定数化、試行ログに `prompt_via` |
| `tests/mock_cli.py` | `--prompt-file` / `--prompt`、`env:NAME` 動作 |
| `tests/test_runner.py` / `tests/test_tournament.py` | テスト追加・修正（計120件） |
| `config/models.example.yaml` | 実CLI4件の設定例（無効） |
| `SPEC.md` | 5.1 確認済みCLI表、5.2 プロンプトの渡し方・env、6.1、7、9.1、9.3、9.4、13、14 |
| `README.md` | 実AI CLIの準備状況、未確認点、承認チェックリスト |
| `config/models.yaml` | ローカルのみ作成（Git 管理外） |

## 8. 既知の未解決事項
- 各CLIの廉価モデルの実際のモデルID。
- ツール無効化オプションが実際に効くか（4CLIとも未検証）。
- 各CLIの回答が標準出力にそのまま出るか、JSON 出力のフィールド名、トークン・費用の取得方法。
- Codex はシェル実行を止めるオプションがヘルプになく、方針により大会から除外している。
- `-p` 時に Claude Code が標準入力を読むか（設定例では引数渡しにしたので現状は影響なし）。
- PermissionError の原因（未確定。ログで追跡する）。
- Grok の xAI API ラッパー（Q-20）は不要の見込み（CLI が存在するため）だが、CLI の実動作は未確認。
- 自動PASSオプション、`board_delivery: file`、並列実行は未実装（従来どおり）。

## 9. 次回の有料テスト前に必要な判断（ユーザー）
1. **どのCLI・どの廉価モデル2種類で試すか**（Q-18）。候補は Claude Code・Gemini・Grok。Codex は現状のオプションでは除外。
2. **サンドボックスの確認方法をどうするか**。案: 検証用プロンプト（例「カレントディレクトリにファイルを作って」）を1回だけ送り、作業ディレクトリに変化がないことを確認する。これも課金が発生するので承認が必要。
3. **疎通確認の実行承認**: `py main.py validate --live --allow-unrestricted --yes` を対象モデルで1回（1モデル1呼び出し）。
4. **1局あたりの費用の目安を許容できるか**。1局で通常60〜70回呼び出す。Claude Code は `--max-budget-usd`（設定例では1回 0.05ドル）で1回あたりの上限を付けられる（ヘルプ記載。未検証）。
5. Codex を対象に含めたい場合、外部の隔離環境で動かすなど別の抑止策を採るか。

## 10. コミット
- 実装: `91ba338` feat: prepare real AI CLI integration without model calls（`main` に push 済み、`3b22681..91ba338`）
- 作業中にリモートへ `3b22681`（Instruction00003.md 追加）が push されていたため、`git pull --rebase` してから push した。衝突はなかった。
- 本ファイル（Result00002.md）と dream.md は、この後の別コミットで push する。
