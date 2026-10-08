# AI-Othello 仕様書（SPEC）

Version 0.2 / 2026-10-08

- 正本: [RequiredSpecifications.md](./RequiredSpecifications.md)
- 回答済みの不明点: [QandA.md](./QandA.md)（Q-01〜Q-22。すべて本書に反映済み）
- 優先順位: 正本 → QandA.md の回答 → 本書。矛盾があれば上位に従う。

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
- レーティング（Elo等）の算出
- 対局の並列実行（将来対応。Q-14）

### 1.3 動作環境
- Python 3.11 以降
- 操作はすべてCLI
- 文字コードはUTF-8（Windowsでも `encoding="utf-8"` を明示して読み書きする）

---

## 2. 用語

| 用語 | 定義 |
|---|---|
| プレイヤー | 設定ファイルに登録された1モデル。一意の `model_id` で識別する |
| 手番 | 一方のプレイヤーが1回の着手（またはPASS）を確定させるまでの区間 |
| 試行（attempt） | 手番内でAI CLIを1回呼び出すこと |
| 反則（foul） | AIの回答がルール・形式に反すること（4.3節）。プレイヤーごとに1局で累積する |
| 技術エラー | CLIのタイムアウト、認証失敗、非ゼロ終了など、回答内容以前の失敗（4.4節） |
| 技術中断 | 技術エラーが1手番のリトライ上限を超えて対局を打ち切ること。通常の勝敗から除外する |
| 反則負け | 1局での累積反則が10回に達して負けとなること |

---

## 3. 盤面とルール

### 3.1 board.txt の形式（Q-01）
- UTF-8、8行×8文字。見出し・座標・空白・手番情報は入れない。
- 書き出しはLF改行で、各行末と最終行末に改行を付ける。
- 読み込みは最終行の改行がなくても受け付ける。8行×8文字の条件は厳守する。

| 状態 | 文字 | コードポイント |
|---|---|---|
| 黒 | `●` | U+25CF BLACK CIRCLE |
| 白 | `〇` | U+3007 IDEOGRAPHIC NUMBER ZERO |
| 空き | `□` | U+25A1 WHITE SQUARE |

注意: 白は `○`（U+25CB）ではなく `〇`（U+3007）である。上記3文字以外を含む盤面、8×8でない盤面、BOM付きの盤面はエラーとする。

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
- 初期盤面の `D4` は白、`E4` は黒、`D5` は黒、`E5` は白。
- この座標系で、初期盤面の黒の合法手は `D3`, `C4`, `F5`, `E6` の4つになる。

### 3.4 対局ルール（標準オセロ）
1. 黒が先手。
2. 着手は空きマスに限る。置いた石から8方向それぞれについて、相手の石が1個以上連続し、その先に自分の石がある場合、その間の相手の石をすべて反転する。複数方向を同時に反転する。
3. 1個以上反転できるマスだけが合法手。
4. 合法手がない場合のみPASSできる。
5. 両者とも合法手がない、または盤面が満杯になったら終局する。
6. 終局時に石が多い方の勝ち。同数は引き分け。

### 3.5 ルールエンジン（game.py）
副作用を持たない純粋関数で実装する。

| 関数 | 内容 |
|---|---|
| `initial_board()` | 初期盤面 |
| `parse_board(text)` / `format_board(board)` | board.txt の文字列と盤面の相互変換（検証込み） |
| `legal_moves(board, color)` | 合法手の一覧（A1, B1, …, H8 の順） |
| `flips_for(board, color, coord)` | 反転する石の一覧 |
| `apply_move(board, color, coord)` | 反転後の新しい盤面。非合法なら `IllegalMoveError`。元の盤面は変えない |
| `is_game_over(board)` / `winner(board)` / `count_stones(board)` | 終局判定・勝者・石数 |
| `coord_to_index` / `index_to_coord` | `D3` ⇔ (行, 列) |
| `board_sha256(board)` | 整合性確認用のハッシュ |

---

## 4. 手番の進行と反則・技術エラー

### 4.1 手番の流れ
```
手番開始（両者とも合法手なし・満杯なら終局）
 └─ 試行ループ
      ├─ AI CLI 呼び出し
      │    ├─ 技術エラー → この手番の技術エラー回数+1
      │    │     ├─ 回数 ≤ リトライ上限(既定3) → 待機して同じ手番で再試行
      │    │     └─ 回数 > リトライ上限 → 技術中断で対局終了
      │    └─ 回答本文を取得 → 判定
      │          ├─ 合法手 / 合法なPASS → 盤面更新して手番終了
      │          └─ 反則 → 累積反則+1（盤面は変えない）
      │                ├─ 累積10回到達 → 即反則負けで対局終了
      │                └─ 10回未満 → 同じ手番で再試行
```

### 4.2 回答形式（Q-05）
- AIの回答は座標1つ（`A1`〜`H8`）または `PASS` のみ。
- 構造化出力（JSON等）を返すCLIは、本文に当たるフィールドだけを取り出す。
- 取り出した本文の前後の空白・改行を除去したうえで、正規表現 `^(?:[A-H][1-8]|PASS)$` に完全一致しなければ形式反則とする。
- 大文字のみ受け付ける。`d3` や `pass` は形式反則。余分な説明文が付いた回答も形式反則。
- 説明文やコードブロックから座標を抜き出して採用することはしない。

### 4.3 反則
| 反則種別 | コード | 条件 |
|---|---|---|
| 形式違反 | `format` | 4.2節の正規表現に一致しない。空の回答（Q-06）や `I9`・`A0`・`Z99` などの盤外座標（Q-07）を含む |
| 違法座標 | `illegal_move` | `A1`〜`H8` の形式は満たすが着手できないマス（石がある、1個も反転できない）。合法手がない手番で座標を返した場合も含む |
| 誤PASS | `wrong_pass` | 合法手があるのに `PASS` を返した |

**反則の上限（最重要）**
- 反則回数はプレイヤーごと・1局ごとに累積する。
- **累積10回に達した時点で即反則負けとする。** 目的は、AIが同じ誤答を繰り返して対局が終わらなくなる無限ループを防ぐこと。
- 途中で合法手を打っても、反則回数はリセットしない。
- 上限値は `config/rules.yaml` の `foul_limit` で変更できる（既定10）。
- 反則回数は成績に表示するが、単純な棋力指標としては扱わない。

**反則後の再試行（Q-08）**
- 盤面を更新せず、同じプレイヤーに同じ手番で再回答させる。
- 再試行のプロンプトは初回とまったく同じにする。反則の説明や合法手のヒントは渡さない。
- 毎回独立したCLIプロセスを起動し、前の回答を引き継がない。

### 4.4 技術エラー
次は反則ではなく技術エラーとして扱う。

| 種別 | コード | 条件 |
|---|---|---|
| 応答タイムアウト | `timeout` | 応答タイムアウト（5.2節）を超えた |
| 非ゼロ終了 | `nonzero_exit` | 終了コードが0以外 |
| 認証失敗 | `auth` | 非ゼロ終了のうち、標準エラー出力から認証失敗と判別できるもの |
| 起動失敗 | `launch` | CLIが見つからない・起動できない |
| 解析失敗 | `parse` | 構造化出力が壊れていて本文を取り出せない（Q-09）。本文は取れたが形式が違う場合は `format` 反則 |

**リトライ上限（Q-22）**
- 技術エラー回数は**手番ごとに独立**して数え、手番が変わるとリセットする。同じ手番の中では、反則を挟んでもリセットしない。
- 初回の呼び出し1回とリトライ最大3回で、1手番の試行は最大4回。4回とも技術エラーなら技術中断とする。
- リトライ上限は `config/rules.yaml` の `technical_retry_limit`（既定3）。
- 技術エラー回数と反則回数は別のカウンタ。

**待機時間（Q-10）**
- 技術エラーの後は 1秒 → 2秒 → 4秒 … と指数的に待機時間を延ばす（上限30秒、`backoff_max_sec`）。
- レート制限などで Retry-After 相当の値が取得できれば、それを優先する（上限は同じ）。

**技術中断**
- 技術中断した対局は勝率の分母に含めず、成績では別に表示する。
- 自動では再実行しない（9.6節）。

### 4.5 合法手がない手番（Q-04）
- 合法手がない場合もAIを呼び出し、`PASS` を回答させる。正しくPASSを返せるかも評価対象とする。
- `PASS` 以外の座標を返したら `illegal_move` 反則。
- 両者とも合法手がない場合は終局なので、AIは呼ばない。
- 費用節約のための自動PASS機能は将来の任意オプションとし、既定では無効（未実装）。

### 4.6 終局と結果
| 結果コード | 内容 |
|---|---|
| `normal` | 通常終局。石数で勝敗・引き分けを決める |
| `foul_loss` | 反則負け。反則したプレイヤーの負け |
| `technical_abort` | 技術中断。勝敗なし。勝率の分母から除外 |

- 反則負け・技術中断の場合も、打ち切り時点の石数は生データとして記録する。
- 反則負けの対局は石差の集計（ランキング）に含めない。64対0への置き換えもしない（Q-11）。

---

## 5. AI呼び出し（ai_runner.py）

### 5.1 プロバイダ
| provider | 内容 | 状態 |
|---|---|---|
| `mock` | テスト用モックCLI（`tests/mock_cli.py`）。課金なし | 実装済み |
| `cli` | 汎用CLIアダプタ。`command` の引数配列で実CLIを起動し、プロンプトを標準入力で渡す | 実装済み（実CLIでは未検証） |

- 実CLIの候補は Claude Code CLI、Codex CLI、Gemini CLI。各CLIのコマンドとモデル指定方法は実行環境の `--help` 等で確認してから設定する。存在しないオプションを推測で使わない。
- Grok（Q-20）: 公式または利用実績のあるCLIが確認できなければ、xAI API を呼ぶ最小限のラッパーを作ってよい。APIキーは環境変数から読み、ログ・Gitに残さない。API経由とCLI経由で比較条件が違うことを記録する。

### 5.2 呼び出し規則
- `subprocess` には引数リストを渡し、`shell=True` を使わない。
- Windows では `claude` / `codex` / `gemini` が npm の `.cmd` ラッパーであることが多いので、`shutil.which()` で実体のパスを解決してから起動する。`.cmd` に引数でプロンプトを渡すとエスケープの問題があるため、プロンプトは標準入力で渡す。
- 着手ごとに独立したCLIプロセスを起動し、前の会話履歴を引き継がない。
- 応答タイムアウトの既定は120秒。モデルごとに `timeout_sec` で上書きできる（思考型モデルは300秒など）（Q-03）。
- タイムアウト時は子プロセスをプロセスツリーごと終了させる（Windowsは `taskkill /T /F`、それ以外はプロセスグループへ SIGKILL）。Ctrl+C の場合も同様。
- CLIは対局ごとの空の作業ディレクトリ（`games/<game_id>/workdir/`）で実行する。
- 標準出力・標準エラー出力・終了コード・所要時間を記録する。

### 5.3 サンドボックス（Q-21）
- 任意コード実行・ファイル編集を許可しない。モデルが自分でプログラムを書いて合法手を計算することも避ける。
- 設定の `sandbox` 項目で制限状況を宣言する: `restricted`（制限を確認済み）/ `unrestricted` / `unknown`（既定。mock は restricted）。
- `restricted` 以外の実CLIは大会（`tournament`）に参加できない。
- 検証目的で1局だけ動かす場合は `play --allow-unrestricted` を明示する。このとき各試行のログに `sandbox_note` として制限できていない旨を記録する。

### 5.4 プロンプト（Q-02）
AIに渡すのは「共通指示」「担当色」「記号の凡例」「座標規則」「盤面」だけとする。合法手一覧・最善手は渡さない。全モデルで同じテンプレートを使い、担当色の部分だけを切り替える。

共通指示（変更不可）:
> あなたはオセロのプレイヤーです。提示された8×8の盤面を読み、指定された色として標準オセロの合法手を1つ選んでください。着手可能な場所がない場合のみPASSを返してください。回答はA1～H8の座標1つ、またはPASSのみ。説明や装飾は付けないでください。

テンプレート:
```text
<共通指示>

あなたの色: 黒（●）        ※白の場合は「白（〇）」
記号: ●=黒、〇=白、□=空き
座標規則: 列は左からA～H、行は上から1～8。例: 左上がA1、右下がH8。

盤面:
<board.txt の内容>
```

### 5.5 盤面の渡し方
- 現在はPythonが盤面テキストをプロンプトに埋め込む方式（`board_delivery: inline`）だけを実装している。
- CLIの読取専用ファイル参照（`board_delivery: file`）は未実装。対応する場合も、使った方式を着手ログに記録する。

### 5.6 出力解析
1. `output: text` なら標準出力全体、`output: json` なら `json_field` で指定したフィールドを本文とする。
2. JSONが壊れている、フィールドがない、文字列でない場合は `parse` 技術エラー。
3. 本文の前後の空白・改行を除去し、4.2節の正規表現で判定する。
4. 生の標準出力・標準エラー出力は常に保存する。

### 5.7 付帯情報
取得できる場合だけ記録し、取得できなければ `null` とする。推測値は記録しない。
- 実モデルID、入力・出力トークン数、費用（`usage_fields` でJSON内のパスを指定）
- CLIのバージョン（`version_command`。課金のない呼び出しのみ）

### 5.8 秘密情報
- APIキー・認証情報を設定ファイル・ログ・Gitに含めない。
- 標準出力・標準エラー出力をログに書く前に、`sk-…`・`xai-…`・`AIza…`・`Bearer …` の形の文字列と、名前に KEY / TOKEN / SECRET / PASSWORD を含む環境変数の値を `***MASKED***` に置き換える。

---

## 6. 設定ファイル

### 6.1 config/models.yaml
- Git管理するのは `config/models.example.yaml` だけ。実際の `config/models.yaml` は `.gitignore` で除外する。

| 項目 | 必須 | 内容 |
|---|---|---|
| `id` | ○ | 一意のID（英数字と `.` `_` `-`） |
| `provider` | ○ | `mock` / `cli` |
| `model` | ○ | CLIに渡すモデル名。`command` 内の `{model}` に入る |
| `command` | ○ | 引数配列。`{python}`（実行中のPython）、`{project}`（リポジトリのルート）、`{model}` を置換する |
| `timeout_sec` | | 応答タイムアウト |
| `output` / `json_field` | | `text`（既定）/ `json` と本文のパス（例: `result`、`choices.0.text`） |
| `usage_fields` | | `actual_model` / `input_tokens` / `output_tokens` / `cost_usd` のJSONパス |
| `version_command` | | バージョン取得コマンド |
| `sandbox` / `sandbox_note` | | 5.3節 |
| `enabled` | | `false` で総当たりの既定対象から外す |

`validate` は、id の重複、必須項目の欠落、未知の provider、`command` が配列でない場合をエラーにする。

### 6.2 config/rules.yaml
```yaml
foul_limit: 10               # 1局・1プレイヤーあたりの累積反則上限。到達で即反則負け
technical_retry_limit: 3     # 1手番あたりのリトライ回数（初回+3回=最大4試行）
default_timeout_sec: 120     # 応答タイムアウトの既定値
backoff_base_sec: 1          # 技術エラー後の待機: 1→2→4秒…
backoff_max_sec: 30          # 待機の上限
games_per_side: 1            # 各組み合わせ・各先後の対局数
```

---

## 7. CLIコマンド（main.py）

共通オプション: `--config`（既定 `config/models.yaml`）、`--rules`（既定 `config/rules.yaml`）、`--games-dir`（既定 `games`）、`--results-dir`（既定 `results`）

| コマンド | 内容 |
|---|---|
| `play --black <id> --white <id>` | 1局だけ対局する。`--resume <game_id>` で再開 |
| `tournament [--models a,b,...] [--games-per-side N]` | 総当たり大会を新規に実行する |
| `tournament --resume <tournament_id> [--retry-aborted]` | 大会を再開する。`--retry-aborted` で技術中断した対局を別IDで再対局する |
| `results [--tournament <id>]` | 成績を集計してCSVに書き、表を表示する |
| `list-models` | 設定済みモデルの一覧 |
| `validate [--live]` | 設定の整合性と各CLIの存在・バージョンを確認する（Q-13）。`--live` を付けたときだけ、各モデルに初期盤面で1手だけ実際に回答させる |

**実CLIの実行確認（Q-19）**
- mock 以外のモデルを呼ぶ前に、対象モデル、対局数、呼び出し回数の目安を表示し、`yes` の入力を求める。`--yes` で省略できる。非対話環境では `--yes` がなければ中止する。
- 費用はCLIが返す実績値だけを記録する。費用の上限は保証しない。ハードな予算管理は、正確な従量データが取得できる場合にだけ追加する。

**終了コード**: 正常0、実行時の異常停止1、設定エラー・実行拒否2、Ctrl+C による中断130。

---

## 8. 総当たり大会（tournament.py）

- 指定モデルの全組み合わせについて、黒白を入れ替えて対局する。
- 同じ `model_id` 同士の自己対戦は含めない。別IDなら同じ会社のモデル同士でも対戦する（Q-12）。
- 各先後の対局数は `games_per_side`（`--games-per-side` で上書き可）。
  - 例: 3モデル、`games_per_side=2` → 3組 × 2先後 × 2局 = 12局。
- 対局は直列に実行する（Q-14）。
- 対局順は大会作成時に決めて `games/_tournaments/<tournament_id>.json` に保存し、再開時も同じ順で進める。
- 1局終わるごとに `results/` のCSVを更新する。

---

## 9. 保存と再開

### 9.1 ディレクトリ構成（Q-15）
```text
games/<game_id>/board.txt               現在の盤面
games/<game_id>/state.json              対局状態
games/<game_id>/moves.jsonl             試行ごとのログ（1行1レコード、追記のみ）
games/<game_id>/moves.discarded.jsonl   再開時に切り捨てた未確定ログ（ある場合のみ）
games/<game_id>/workdir/                AI CLI の作業ディレクトリ
games/_tournaments/<tournament_id>.json 大会の対局予定
results/matches.csv                     対局ごとの結果
results/ranking.csv                     モデルごとの集計
```
- `game_id`: 大会では `<tournament_id>-<black>-vs-<white>-<連番3桁>`、`play` では `<YYYYMMDD-HHMMSS>-<black>-vs-<white>-<連番3桁>`。`tournament_id` は `YYYYMMDD-HHMMSS`。
- `games/` と `results/` の実行時データは `.gitignore` の対象。公開する集計結果は手動で `reports/` などにコピーしてコミットする。

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
  "loser": null,
  "stones": null,
  "fouls": {"black": 2, "white": 0},
  "foul_breakdown": {
    "black": {"format": 1, "illegal_move": 1, "wrong_pass": 0},
    "white": {"format": 0, "illegal_move": 0, "wrong_pass": 0}
  },
  "tech_errors": {"black": 1, "white": 0},
  "turn_tech_errors": 0,
  "turn_attempts": 0,
  "aborted_by": null,
  "board_sha256": "<board.txt の SHA-256>",
  "log_lines": 37,
  "created_at": "2026-10-08T15:48:00+09:00",
  "updated_at": "2026-10-08T15:55:12+09:00",
  "finished_at": null
}
```
- `status`: `in_progress` / `finished` / `technical_abort`
- `result`: `normal` / `foul_loss` / `technical_abort`
- `winner` / `loser` / `aborted_by`: `black` / `white` / `null`（引き分けは winner が null）
- `move_number`: 次の手番の番号（PASSも1手番と数える）

### 9.3 moves.jsonl（1試行1レコード）
| フィールド | 内容 |
|---|---|
| `seq` | 通し番号（1から） |
| `game_id` / `move_number` / `color` / `model_id` / `attempt` | 対局、手番番号、色、モデル、手番内の試行番号 |
| `board_before` | 試行前の盤面 |
| `legal_moves` | その局面の合法手（分析用。AIには渡していない） |
| `prompt` / `board_delivery` | 実際に渡したプロンプト全文と盤面の渡し方 |
| `raw_stdout` / `raw_stderr` / `exit_code` | CLIの生出力（秘密情報はマスク）と終了コード |
| `extracted` | 解析後の回答本文（技術エラー時は null） |
| `outcome` | `move` / `pass` / `foul` / `technical_error` |
| `foul_type` / `error_type` / `error_detail` | 反則・技術エラーの種別と説明 |
| `foul_count_after` | この試行後の累積反則数 |
| `board_after` | 着手した場合の盤面 |
| `elapsed_sec` | 所要時間 |
| `actual_model` / `cli_version` / `input_tokens` / `output_tokens` / `cost_usd` | 取得できた場合のみ。取得できなければ null |
| `sandbox_note` | サンドボックス制限を確認できていない場合の記録 |
| `timestamp` | ISO 8601 |

### 9.4 書き込み順と整合性
- 1試行ごとに「moves.jsonl に追記（fsync）→ board.txt を一時ファイル経由で置換 → state.json を一時ファイル経由で置換」の順で保存する。
- **state.json の置換完了をコミット点とする。** state.json の `log_lines` 行目までが確定済みの試行。
- Windows でファイル置換が一時的に `PermissionError` になる場合（ウイルス対策ソフト等）に備え、置換は短い間隔で数回リトライする。
- 再開時の照合手順:
  1. moves.jsonl のうち `log_lines` を超える行は未確定とみなし、`moves.discarded.jsonl` に退避して切り捨てる。
  2. 初期盤面から確定済みログを再生し、盤面ハッシュ・手番・手番番号・反則数・反則内訳・手番内の技術エラー数と試行数を state.json と照合する。
  3. board.txt が再生結果と違えば、再生結果で書き直す（state.json 更新前に中断したケース）。
  4. ログが state.json より短い、確定済みログが壊れている、照合が一致しない場合は、`StateError` で処理を止める。それ以上の自動修復はしない。

### 9.5 停止と再開
- Ctrl+C やクラッシュで止まった場合、実行中だった試行は記録せずに破棄する。子プロセスは終了させる。
- `play --resume <game_id>` で1局を、`tournament --resume <tournament_id>` で大会を再開する。
- 大会の再開では、未完了の対局をその手番から続行し、未着手の対局を予定順に実行する。終了済み・技術中断済みの対局はやり直さない。
- 再開時のプレイヤーが保存済みの対局と違う場合は止める。

### 9.6 技術中断した対局の再対局（Q-16）
- 自動では再実行しない。技術中断はそのまま記録する。
- `tournament --resume <id> --retry-aborted` を指定したときだけ、技術中断した対局ごとに別の対局ID（`<元のID>-r1`）で再対局を予定に追加する。元の中断ログは残す。
- 成績では、元の対局は技術中断として、再対局は通常の対局として数える。

---

## 10. 成績集計（statistics.py）

### 10.1 results/matches.csv（1対局1行）
`tournament_id, game_id, black, white, result_type, winner, loser, black_stones, white_stones, stone_diff, moves, black_fouls, white_fouls, black_foul_format, black_foul_illegal, black_foul_wrong_pass, white_foul_format, white_foul_illegal, white_foul_wrong_pass, black_tech_errors, white_tech_errors, aborted_by, black_avg_sec, white_avg_sec, black_tokens, white_tokens, black_cost_usd, white_cost_usd, started_at, finished_at`

- `result_type` は `normal` / `foul_loss` / `technical_abort` / `in_progress`。
- `winner` は勝者のモデルID。引き分けは `draw`。
- `stone_diff` は黒−白（生データ。反則負け・技術中断でも打ち切り時点の値を記録）。
- `moves` はPASSを含む手番数。

### 10.2 results/ranking.csv（1モデル1行）
| 列 | 内容 |
|---|---|
| `model_id` | モデルID |
| `games` | 対局数（技術中断・進行中を除く） |
| `wins` / `losses` / `draws` | 勝・負・分 |
| `win_rate` | (勝 + 0.5×分) ÷ 対局数 |
| `games_black` / `win_rate_black` / `games_white` / `win_rate_white` | 先手・後手別の対局数と勝率 |
| `stone_diff_total` / `stone_diff_avg` / `stone_diff_games` | 自分−相手の石差の合計・平均・対象局数。通常終局の対局だけを集計し、反則負けの対局は含めない（Q-11） |
| `foul_losses` | 反則負け数 |
| `fouls_illegal` / `fouls_wrong_pass` / `fouls_format` | 反則内訳 |
| `avg_response_sec` / `response_samples` | 平均応答時間と対象試行数。回答本文を取得できた試行（合法手・PASS・反則回答）だけを対象にする（Q-17） |
| `tech_errors` / `tech_error_avg_sec` | 技術エラーの件数と平均所要時間 |
| `tech_aborts` | 自分の技術エラーで中断した対局数（勝率とは別に表示） |
| `tokens` / `tokens_games` / `cost_usd` / `cost_games` | 取得できた値の合計と、取得できた対局数。取得できなければ空欄 |

- 並び順は勝率の高い順、同率なら石差平均の高い順。
- 費用・トークンは推測値と実績を混同しない。

---

## 11. セキュリティ・Git管理
- `.gitignore`: `games/`, `results/`, `config/models.yaml`, `.env`, `__pycache__/`, `.pytest_cache/` など。
- 一時ファイル・ログ・キャッシュはプロジェクト配下（Cドライブ）に作る。

---

## 12. 自動テスト

| ファイル | 内容 |
|---|---|
| `tests/test_game.py` | 初期盤面と文字コード、board.txt の検証、座標変換、黒白の初手合法手、8方向それぞれと全方向同時の反転、違法着手で盤面不変、片側だけ打てない局面、両者合法手なしで終局、満杯・引き分け・勝者判定 |
| `tests/test_runner.py` | プロンプトの内容（合法手を含まない、色だけが違う）、回答形式の判定、空白除去、説明文から座標を抜かないこと、JSON抽出と解析失敗、設定の検証、秘密情報のマスク。モックCLIで正常手・形式違反・空回答・JSON・壊れたJSON・タイムアウト・非ゼロ終了・認証エラー・起動失敗 |
| `tests/test_tournament.py` | 回答判定（合法PASS・誤PASS含む）、待機時間、反則1〜9回は同じ手番で再試行・10回目で即反則負け・合法着手で累積を維持・上限の設定変更・反則内訳、技術エラーのリトライと技術中断・手番ごとのリセット・反則との独立、モックCLIのプロセスで1局完走（PASSを含む）、停止・再開、未確定ログの切り捨て、改ざん検出、総当たりと黒白交換、CSV集計、勝率の計算、大会の中断・再開、技術中断の再対局、main.py の各コマンド、実CLIの確認とサンドボックスによる拒否 |

- 実CLIを使うテストは `@pytest.mark.real_cli` を付け、既定では実行しない（`pytest.ini` で除外）。
- 実際に `pytest` を実行し、成功・失敗・未実施を区別して報告する。実行していないテストを実行済みと報告しない。

---

## 13. 実装ファイル
```text
main.py                     CLI: play / tournament / results / list-models / validate
game.py                     ルール判定・盤面入出力（純粋関数）
ai_runner.py                CLIアダプタ・出力解析・タイムアウト・秘密情報マスク
tournament.py               対局進行、反則・技術エラー管理、保存、再開、総当たり
statistics.py               CSV集計
config/models.example.yaml  モデル設定の例（モックのみ有効）
config/rules.yaml           反則上限・技術リトライ上限・待機時間・対局数
tests/test_game.py
tests/test_runner.py
tests/test_tournament.py
tests/mock_cli.py           テスト用モックCLI
pytest.ini
requirements.txt            PyYAML, pytest
.gitignore
```
注意: `statistics.py` は Python 標準ライブラリの `statistics` と同じ名前なので、リポジトリのルートを `sys.path` に入れると標準ライブラリ側を隠す。正本のファイル名に従っているが、標準の `statistics` が必要になった場合は改名を検討する。

---

## 14. 実装手順と進捗
1. リポジトリとCLI環境の確認 — 済み（claude / codex / gemini / grok のコマンドが存在することだけを確認。`--help` による実際のオプションの確認と実行はしていない）
2. `game.py` とテスト — 済み
3. モックCLIで対局、累積反則10回、技術中断、ログ、再開、総当たり、CSV — 済み
4. 実CLIの組み込み — 未着手。ユーザーの許可を得てから、廉価モデル合計2種類で1局だけ試す（Q-18）
5. README の更新 — 済み（実装範囲に合わせて随時更新）
6. 作業報告 — `instructions/ResultXXXXX.md` に記録する
