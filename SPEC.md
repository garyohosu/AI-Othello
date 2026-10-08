# AI-Othello 仕様書（SPEC）

Version 0.1 / 2026-10-08
正本: [RequiredSpecifications.md](./RequiredSpecifications.md)（本書と矛盾する場合は正本を優先する）
未確定事項: [QandA.md](./QandA.md)（本書で「暫定」と書いた項目は QandA.md の回答で確定させる）

---

## 1. 目的と範囲

### 1.1 目的
複数のAIモデル（ChatGPT/Codex、Claude、Gemini、Grok など）をCLIから呼び出し、Pythonが審判となってオセロの対局と総当たり大会を行う。次の項目を比較する。

- 棋力（勝敗・石差）
- 指示遵守（反則の回数と内訳）
- 応答速度
- CLIの安定性（技術エラー・技術中断）
- 費用・トークン数（取得できる場合のみ）

### 1.2 範囲外
- GUI
- Claude Code 自身に対局の着手判断を代行させること（Claude Code は実装・操作のみに使う）
- AIへの合法手一覧・最善手・評価値の提示
- レーティング（Elo等）の算出（必須ではない）

### 1.3 動作環境
- Python 3.11 以降
- 操作はすべてCLI
- 文字コードはUTF-8（Windows環境でも `encoding="utf-8"` を明示して読み書きする）

---

## 2. 用語

| 用語 | 定義 |
|---|---|
| プレイヤー | 設定ファイルに登録された1モデル。一意の `model_id` で識別する |
| 手番 | 一方のプレイヤーが1回の着手（またはPASS）を確定させるまでの区間 |
| 試行（attempt） | 手番内でAI CLIを1回呼び出すこと |
| 反則（foul） | AIの回答がルール・形式に反すること（4.3節）。プレイヤーごとに1局で累積する |
| 技術エラー | CLIのタイムアウト、認証失敗、非ゼロ終了など、回答内容以前の失敗（4.4節） |
| 技術中断 | 技術エラーが1手番の上限に達して対局を打ち切ること。通常の勝敗から除外する |
| 反則負け | 1局での累積反則が10回に達して負けとなること |

---

## 3. 盤面とルール

### 3.1 board.txt の形式
- UTF-8、8行×8文字。見出し・座標・空白・手番情報は入れない。
- 各行の末尾は改行（`\n`）。最終行の末尾にも改行を付ける（暫定、QandA Q-01）。

| 状態 | 文字 | コードポイント |
|---|---|---|
| 黒 | `●` | U+25CF BLACK CIRCLE |
| 白 | `〇` | U+3007 IDEOGRAPHIC NUMBER ZERO |
| 空き | `□` | U+25A1 WHITE SQUARE |

注意: 白は `○`（U+25CB）ではなく `〇`（U+3007）である。読み込み時に上記3文字以外を含む盤面、または8×8でない盤面はエラーとし、安全に停止する。

### 3.2 初期盤面
```text
□□□□□□□□
□□□□□□□□
□□□□□□□□
□□□〇●□□□
□□□●〇□□□
□□□□□□□□
□□□□□□□□
□□□□□□□□
```

### 3.3 座標系
- 列は左から `A`〜`H`、行は上から `1`〜`8`。
- board.txt の1行目が行1、各行の1文字目が列A。
- 例: 初期盤面の `D4` は白、`E4` は黒、`D5` は黒、`E5` は白。
- この座標系で、初期盤面の黒の合法手は `D3`, `C4`, `F5`, `E6` の4つになる。

### 3.4 対局ルール（標準オセロ）
1. 黒が先手。
2. 着手は空きマスに限る。置いた石から8方向それぞれについて、相手の石が1個以上連続し、その先に自分の石がある場合、その間の相手の石をすべて反転する。複数方向を同時に反転する。
3. 1個以上反転できるマスだけが合法手。
4. 合法手がない場合のみPASSできる。
5. 両者とも合法手がない、または盤面が満杯になったら終局する。
6. 終局時に石が多い方の勝ち。同数は引き分け。

### 3.5 ルールエンジン（game.py）
副作用を持たない純粋関数で実装する。最低限次の機能を持つ。

| 関数（例） | 内容 |
|---|---|
| `initial_board()` | 初期盤面を返す |
| `parse_board(text)` / `format_board(board)` | board.txt の文字列と内部表現の相互変換（検証込み） |
| `legal_moves(board, color)` | 合法手の一覧 |
| `apply_move(board, color, coord)` | 反転後の新しい盤面を返す。非合法なら例外。元の盤面は変更しない |
| `is_game_over(board)` | 終局判定 |
| `count_stones(board)` | 黒・白・空きの数 |
| `coord_to_index` / `index_to_coord` | `D3` ⇔ (行, 列) の変換 |

---

## 4. 手番の進行と反則・技術エラー

### 4.1 手番の流れ
```
手番開始
 └─ 試行ループ
      ├─ AI CLI 呼び出し
      │    ├─ 技術エラー → 技術エラー回数+1
      │    │     ├─ リトライ回数が上限(既定3)未満 → 同じ手番で再試行
      │    │     └─ リトライ上限を使い切った → 技術中断で対局終了
      │    └─ 正常終了 → 出力解析・判定
      │          ├─ 合法手 / 合法なPASS → 盤面更新して手番終了
      │          └─ 反則 → 累積反則+1（盤面は変えない）
      │                ├─ 累積10回到達 → 即反則負けで対局終了
      │                └─ 10回未満 → 同じ手番で再試行
```

### 4.2 回答形式
- AIの回答は座標1つ（`A1`〜`H8`）または `PASS` のみ。
- 構造化出力（JSON等）を返すCLIは、本文に当たるフィールドだけを取り出す。
- 取り出した本文の前後の空白・改行を除去したうえで、正規表現 `^(?:[A-H][1-8]|PASS)$` に完全一致しなければ形式反則とする。
- 大文字化などの正規化はしない（暫定、QandA Q-05）。小文字の `d3` は形式反則とする。
- 説明文やコードブロックから座標を抜き出して採用することはしない。

### 4.3 反則
| 反則種別 | コード | 条件 |
|---|---|---|
| 形式違反 | `format` | 4.2節の正規表現に一致しない（空文字を含む。暫定、QandA Q-06） |
| 違法座標 | `illegal_move` | 形式は正しいが、既に石があるマス、または1個も反転できないマス |
| 誤PASS | `wrong_pass` | 合法手があるのに `PASS` を返した |

- 「盤外座標」は正規表現で弾かれるため `format` に分類する（暫定、QandA Q-07）。
- 反則時は盤面を更新せず、同じプレイヤーに同じ手番で再回答させる。
- 反則回数はプレイヤーごと・1局ごとに累積し、途中で合法手を打ってもリセットしない。
- **累積10回に達した時点で即反則負け**とする。上限値は `config/rules.yaml` で設定可能（既定10）。
- 反則回数は成績に表示するが、単純な棋力指標としては扱わない。
- 再試行時のプロンプトは初回と同一とし、反則の内容は伝えない（暫定、QandA Q-08）。

### 4.4 技術エラー
次は反則ではなく技術エラーとして扱う。

| 種別 | コード |
|---|---|
| 応答タイムアウト | `timeout` |
| 非ゼロ終了 | `nonzero_exit` |
| 認証失敗（終了コードや標準エラー出力から判別できる場合） | `auth` |
| CLIが見つからない・起動できない | `launch` |
| 構造化出力の解析失敗（JSONが壊れている等） | `parse` （暫定、QandA Q-09） |

- 技術エラー回数は**手番ごとに独立**して数え、手番が変わるとリセットする。
- 上限は「リトライ回数」として `config/rules.yaml` で設定する（既定3）。初回の試行に加えて最大3回リトライし、1手番あたり4回連続で技術エラーになったら「技術中断」として対局を終了する（暫定、QandA Q-22）。
  - 例: 2回失敗して3回目に成功 → 継続。4回連続で失敗 → 技術中断。
- 技術中断した対局は勝率の分母に含めず、成績では別に表示する。
- 再試行の間隔は既定1秒（暫定、QandA Q-10）。

### 4.5 合法手がない手番
- 暫定として、合法手がない場合もAIを呼び出し、`PASS` を返せば合法とする（QandA Q-04）。
- このとき座標を返した場合は `illegal_move` の反則とする。

### 4.6 終局と結果
| 結果コード | 内容 |
|---|---|
| `normal` | 通常終局。石数で勝敗・引き分けを決める |
| `foul_loss` | 反則負け。反則したプレイヤーの負け |
| `technical_abort` | 技術中断。勝敗なし、勝率の分母から除外 |

- 反則負け時の石差は、打ち切り時点の盤面の石数で記録する（暫定、QandA Q-11）。

---

## 5. AI呼び出し（ai_runner.py）

### 5.1 アダプタ
- プロバイダごとにアダプタを実装する。候補は Claude Code CLI、Codex CLI、Gemini CLI。
- Grok は実際に利用できるCLI/APIを確認してから追加する。
- 各CLIのコマンドとモデル指定方法は実行環境の `--help` 等で確認する。存在しないオプションを推測で使わない。
- テスト用にモックCLIアダプタ（またはモックCLIスクリプト）を用意する。

### 5.2 呼び出し規則
- `subprocess` には引数リストを渡し、原則 `shell=True` を使わない。
- 着手ごとに独立したCLIプロセスを起動し、前の会話履歴を引き継がない。
- 応答タイムアウトを設ける（モデルごとに設定可能。既定値は暫定120秒、QandA Q-03）。
- タイムアウト時は子プロセスを確実に終了させる。CLIが子プロセスを起動する場合に備え、プロセスツリーごと終了させる（Windowsでは `taskkill /T /F` 相当）。
- Windowsでは `claude` / `codex` / `gemini` が npm の `.cmd` ラッパーであることが多い。`shell=True` を使わずに起動するため、`shutil.which()` で実体のパスを解決してから引数リストに渡す。
- 任意コード実行・ファイル編集はCLIのオプションで禁止する。CLIの仕様上制限できない場合は、その事実をログに記録する。
- 標準出力・標準エラー出力・終了コード・所要時間を記録する。

### 5.3 プロンプト
AIに渡すのは「盤面」「担当色」「座標規則」「共通指示」だけとする。合法手一覧・最善手は渡さない。

共通指示（全モデル同一、変更不可）:
> あなたはオセロのプレイヤーです。提示された8×8の盤面を読み、指定された色として標準オセロの合法手を1つ選んでください。着手可能な場所がない場合のみPASSを返してください。回答はA1～H8の座標1つ、またはPASSのみ。説明や装飾は付けないでください。

プロンプト全体のテンプレート（暫定、QandA Q-02）:
```text
<共通指示>

あなたの色: 黒（●）   ※白の場合は「白（〇）」
記号: ●=黒、〇=白、□=空き
座標規則: 列は左からA～H、行は上から1～8。例: 左上がA1、右下がH8。

盤面:
<board.txt の内容>
```

### 5.4 盤面の渡し方
- CLIが読取専用のファイル参照に対応していれば `board.txt` を参照させる。
- 対応していなければ、Pythonが `board.txt` を読み、同じテキストをプロンプトに埋め込む。
- どちらの方式を使ったかを `board_delivery`（`file` / `inline`）として着手ログに記録する。

### 5.5 出力解析
1. 構造化出力なら本文フィールドを抽出する（抽出に失敗したら 4.4節の `parse`）。
2. 前後の空白・改行を除去する。
3. 4.2節の正規表現で判定する。
4. 生回答（未加工の標準出力）は必ずそのまま保存する。

### 5.6 取得する付帯情報
取得できる場合だけ記録し、取得できない項目は `null` とする。推測値は記録しない。
- 実モデルID（CLIが返したもの）
- CLIのバージョン（`--version` 等で取得）
- 入力・出力トークン数
- 費用（CLIが返す値のみ）

---

## 6. 設定ファイル

### 6.1 config/models.yaml
- Git管理するのは `config/models.example.yaml` のみ。実際の `config/models.yaml` は `.gitignore` で除外する。
- APIキーや認証情報は設定ファイルに書かず、環境変数や各CLIのログイン状態を使う。

```yaml
models:
  - id: claude-haiku          # 一意のID（必須）
    provider: claude_code     # アダプタ種別（必須）
    model: <CLIに渡すモデル名> # 必須
    command: ["claude", "-p"] # 実行コマンドの引数配列（必須。実際のオプションは --help で確認）
    timeout_sec: 120          # 任意
    enabled: true             # 任意（既定 true）
  - id: mock-random
    provider: mock
    model: random
    command: ["python", "tests/mock_cli.py", "--mode", "random"]
```

- `id` の重複、未知の `provider`、`command` が配列でない場合は `validate` でエラーにする。

### 6.2 config/rules.yaml
```yaml
foul_limit: 10               # 1局あたりの累積反則上限（到達で反則負け）
technical_retry_limit: 3     # 1手番あたりのリトライ回数（初回+3回=最大4試行。使い切ると技術中断）
default_timeout_sec: 120     # 応答タイムアウト既定値（暫定）
retry_interval_sec: 1        # 技術エラー後の再試行間隔（暫定）
games_per_side: 1            # 各組み合わせ・各先後の対局数
```

---

## 7. CLIコマンド（main.py）

| コマンド | 内容 |
|---|---|
| `play --black <id> --white <id>` | 1局だけ対局する |
| `tournament [--models id1,id2,...] [--games-per-side N] [--resume <tournament_id>]` | 総当たり大会を実行・再開する |
| `results [--tournament <id>]` | `results/*.csv` から成績表を表示する |
| `list-models` | 設定済みモデルの一覧を表示する |
| `validate` | 設定ファイルの検証と、各CLIの存在・バージョン確認を行う（暫定、QandA Q-13） |

- 終了コード: 正常0、設定エラー2、実行中の異常停止1（暫定）。

---

## 8. 総当たり大会（tournament.py）

- 有効な全モデルの組み合わせ（自己対戦は除く。暫定、QandA Q-12）ごとに、黒白を入れ替えて対局する。
- 各先後の対局数は `games_per_side`（CLI引数で上書き可）。
  - 例: 3モデル、`games_per_side=2` → 3組 × 2先後 × 2局 = 12局。
- 対局は直列に実行する（暫定、QandA Q-14）。
- 対局順は事前に決めて大会ファイルに保存し、再開時も同じ順に進める。

---

## 9. 保存と再開

### 9.1 ディレクトリ構成
```text
games/<game_id>/board.txt     現在の盤面（AIに渡す盤面そのもの）
games/<game_id>/state.json    対局状態
games/<game_id>/moves.jsonl   試行ごとのログ（1行1レコード、追記のみ）
results/matches.csv           対局ごとの結果
results/ranking.csv           モデルごとの集計
```
- `game_id` は `YYYYMMDD-HHMMSS-<black>-vs-<white>-<連番>` 形式（暫定）。
- `games/` と `results/` の生データはGit管理から除外する（`results/` の扱いは暫定、QandA Q-15）。

### 9.2 state.json（例）
```json
{
  "game_id": "20261008-154800-model-a-vs-model-b-001",
  "tournament_id": "20261008-154800",
  "black": "model-a",
  "white": "model-b",
  "turn": "black",
  "move_number": 12,
  "status": "in_progress",
  "result": null,
  "winner": null,
  "fouls": {"black": 2, "white": 0},
  "foul_breakdown": {
    "black": {"format": 1, "illegal_move": 1, "wrong_pass": 0},
    "white": {"format": 0, "illegal_move": 0, "wrong_pass": 0}
  },
  "board_sha256": "<board.txt の SHA-256>",
  "log_lines": 37,
  "created_at": "2026-10-08T15:48:00+09:00",
  "updated_at": "2026-10-08T15:55:12+09:00"
}
```
`status` は `in_progress` / `finished` / `technical_abort`。

### 9.3 moves.jsonl（1試行1レコード）
| フィールド | 内容 |
|---|---|
| `seq` | 通し番号 |
| `move_number` | 手番番号 |
| `color` / `model_id` | 手番の色とモデル |
| `attempt` | 手番内の試行番号 |
| `board_before` | 試行前の盤面（8行の文字列） |
| `prompt` | 実際に渡したプロンプト全文 |
| `board_delivery` | `file` / `inline` |
| `raw_stdout` / `raw_stderr` / `exit_code` | CLIの生出力と終了コード |
| `extracted` | 解析後の回答文字列 |
| `outcome` | `move` / `pass` / `foul` / `technical_error` |
| `foul_type` / `error_type` | 該当する場合の種別 |
| `foul_count_after` | この試行後の累積反則数 |
| `board_after` | 盤面を更新した場合の盤面 |
| `elapsed_sec` | 応答時間 |
| `actual_model` / `cli_version` / `input_tokens` / `output_tokens` / `cost_usd` | 取得できた場合のみ、取得できなければ `null` |
| `sandbox_note` | ファイル編集・コード実行を制限できなかった場合の記録 |
| `timestamp` | ISO 8601 |

ログに認証情報を含めない。環境変数や標準エラー出力にキーらしき文字列が含まれる場合はマスクする。

### 9.4 整合性の保証
- 書き込み順は「moves.jsonl に追記 → board.txt を一時ファイル経由で置換 → state.json を一時ファイル経由で置換」とする。
- state.json に盤面のハッシュ（`board_sha256`）とログ行数（`log_lines`）を持たせる。
- **state.json の置換完了をコミット点とする。** state.json に記録された `log_lines` 行目までが確定済みの試行である。
- 再開時の照合手順:
  1. moves.jsonl のうち `log_lines` を超える行は未確定の試行とみなして切り捨てる（切り捨てた行は `moves.discarded.jsonl` に退避して記録を残す）。
  2. board.txt のハッシュが state.json の `board_sha256` と一致しない場合は、確定済みログの最終盤面で board.txt を書き直す（state.json 更新前に中断したケース）。
  3. 初期盤面から確定済みログを再生した盤面、board.txt、state.json の三者を照合する。
  4. 1〜2 の後も不一致が残る場合（ログ自体の破損、手動編集など）は処理を止めてエラーを表示し、それ以上の自動修復はしない。

### 9.5 停止と再開
- Ctrl+C やクラッシュで停止した場合、実行中の試行は破棄し、直前に確定した状態（state.json）から再開する。書き込み途中で止まった場合は 9.4 の手順で未確定分を切り捨てる。
- 再開時は未完了の対局をその手番から続行し、未着手の対局を順に実行する。
- 技術中断した対局は再開時に再実行しない（暫定、QandA Q-16）。

---

## 10. 成績集計（statistics.py）

### 10.1 results/matches.csv（1対局1行）
`tournament_id, game_id, black, white, result_type, winner, black_stones, white_stones, stone_diff, moves, black_fouls, white_fouls, black_foul_format, black_foul_illegal, black_foul_wrong_pass, white_foul_format, white_foul_illegal, white_foul_wrong_pass, black_tech_errors, white_tech_errors, black_avg_sec, white_avg_sec, black_tokens, white_tokens, black_cost, white_cost, started_at, finished_at`

### 10.2 results/ranking.csv（1モデル1行）
| 列 | 内容 |
|---|---|
| `model_id` | モデルID |
| `games` | 対局数（技術中断を除く） |
| `wins` / `losses` / `draws` | 勝・負・分 |
| `win_rate` | (勝 + 0.5×分) ÷ 対局数（技術中断は分母に含めない） |
| `win_rate_black` / `win_rate_white` | 先手・後手別の勝率 |
| `stone_diff_total` / `stone_diff_avg` | 石差の合計・平均 |
| `foul_losses` | 反則負け数 |
| `fouls_illegal` / `fouls_wrong_pass` / `fouls_format` | 反則内訳 |
| `avg_response_sec` | 平均応答時間（全試行の平均。暫定、QandA Q-17） |
| `tech_errors` / `tech_aborts` | 技術エラー数・技術中断数（別表示） |
| `tokens` / `cost` | 取得できた場合のみ。取得できない場合は空欄 |

- 並び順は勝率降順、同率なら石差平均降順（暫定）。
- 費用・トークンは推測値と実績を混同しない。一部の対局しか取得できなかった場合は、取得できた対局数も併記する。

---

## 11. セキュリティ・Git管理
- APIキー・認証情報をログ・設定ファイル・Gitに含めない。
- `.gitignore` に次を含める: `games/`, `config/models.yaml`, `.env`, `__pycache__/`, `.pytest_cache/`。
- 一時ファイル・ログ・キャッシュはプロジェクト配下（Cドライブ）に作る。

---

## 12. 自動テスト

| ファイル | 内容 |
|---|---|
| `tests/test_game.py` | 初期盤面、黒の初手合法手（D3, C4, F5, E6）、8方向それぞれの反転、複数方向の同時反転、違法着手で盤面不変、合法PASSと誤PASS、両者合法手なしで終局、満杯で終局、石数と引き分け |
| `tests/test_runner.py` | モックCLIで正常手、形式違反、無応答、タイムアウト、非ゼロ終了、技術中断を再現。構造化出力の本文抽出、前後空白の除去、説明文付き回答が形式反則になること |
| `tests/test_tournament.py` | 反則1〜9回は同じ手番で再試行、10回目で即反則負け、途中の合法着手で累積が維持されること。モック2モデルで1局完走、黒白交換、総当たりCSV、ログと盤面の整合性、停止・再開、不整合検出時の停止 |

- 実際に `pytest` を実行し、成功・失敗・未実施を区別して報告する。実行していないテストを実行済みと報告しない。
- 実CLIを使うテストはマーカー（例: `@pytest.mark.real_cli`）で分け、既定では実行しない。

---

## 13. 実装ファイル
```text
main.py                     CLI: play / tournament / results / list-models / validate
game.py                     ルール判定・盤面入出力（純粋関数）
ai_runner.py                CLIアダプタ・出力解析・タイムアウト
tournament.py               対局進行、先後交代、保存、再開、反則管理
statistics.py               CSV集計
config/models.example.yaml  モデル設定の例
config/rules.yaml           反則上限・技術エラー上限・対局数など
tests/test_game.py
tests/test_runner.py
tests/test_tournament.py
tests/mock_cli.py           テスト用モックCLI
requirements.txt            PyYAML, pytest
.gitignore
```

---

## 14. 実装手順
1. リポジトリとCLI環境（claude / codex / gemini 等の有無とバージョン、`--help`）を確認する。
2. `game.py` と `tests/test_game.py` を先に作り、合法手と反転の正しさを確かめる。
3. モックCLIで対局、累積反則10回、技術中断、ログ、再開、総当たり、CSVを完成させる。
4. 確認できた実CLIを順に組み込む。廉価モデル2種類で費用を確認し、1局だけ試す（QandA Q-18）。
5. README に実際のセットアップ手順、実行コマンド、制限事項を追記する。
6. 作業報告には、変更ファイル、実行したテストコマンド、実際の結果、残課題を書く。
