# AI-Othello

Pythonを審判役として、CLIから起動する複数のAIモデル同士をオセロで対戦させる比較ツール。

- [必須仕様・Claude Code実装指示書（RequiredSpecifications.md）](./RequiredSpecifications.md) — 正本
- [仕様書（SPEC.md）](./SPEC.md)
- [Q&A（QandA.md）](./QandA.md) — 仕様の不明点と回答
- [作業指示と結果報告（instructions/）](./instructions/)

## 目標
- ChatGPT/Codex、Claude、Gemini、Grokなどのモデルを設定によって追加
- `●` `〇` `□` の8×8テキスト盤面を読み、各AIが座標または `PASS` を返す
- Pythonが合法手判定・反転・終局・反則を一元管理
- 全モデル総当たり、黒白交換、勝敗・反則・応答時間をCSV集計
- AIの生回答と盤面を保存し、後から誤回答を検証できる

## 反則（確定）
違法な着手、形式不正、打てる手があるときのPASSは反則。盤面を変えず同じ手番で再試行する。**1局で同じAIの反則が累積10回になったら反則負け。** 無限ループ防止のためであり、合法着手を挟んでもリセットしない。CLI起動エラー・タイムアウトなどは反則ではなく技術エラーとして扱い、1手番に4回続いたら技術中断（勝敗から除外）とする。

## 開発状況（2026-10-08 時点）
| 項目 | 状態 |
|---|---|
| ルールエンジン（`game.py`） | 実装済み・テスト済み |
| 対局管理・反則/技術エラー・保存/再開・総当たり・CSV集計 | 実装済み・モックCLIでテスト済み |
| 実AI CLI（Claude Code / Codex / Gemini / Grok） | **未接続・未検証**。汎用CLIアダプタはあるが、実CLIでは一度も動かしていない |

## セットアップ
Python 3.11 以降が必要。

```powershell
git clone https://github.com/garyohosu/AI-Othello.git
cd AI-Othello
py -m pip install -r requirements.txt
copy config\models.example.yaml config\models.yaml
```

Windows では `python` コマンドが Microsoft Store のスタブになっている場合がある。その場合は `py` を使う。

## 使い方
`config/models.example.yaml` には課金のないモックモデル（`mock-first`、`mock-json`）だけが有効になっている。

```powershell
# 設定とCLIの存在を確認（AIは呼ばない）
py main.py validate

# モデル一覧
py main.py list-models

# 1局だけ対局
py main.py play --black mock-first --white mock-json

# 総当たり（黒白を入れ替えて各1局）
py main.py tournament --models mock-first,mock-json --games-per-side 1

# 成績を集計して表示（results/matches.csv, results/ranking.csv）
py main.py results

# Ctrl+C で止めた対局・大会の再開
py main.py play --resume <game_id>
py main.py tournament --resume <tournament_id>

# 技術中断した対局を別IDで再対局
py main.py tournament --resume <tournament_id> --retry-aborted
```

対局データは `games/<game_id>/`（`board.txt`、`state.json`、`moves.jsonl`）に保存される。`games/` と `results/` は Git 管理外。

## テスト
```powershell
py -m pytest
```
実CLIを呼ぶテストは `real_cli` マーカーで既定から除外している（現時点では該当テストなし）。

## 実CLIを使うときの注意
- 各CLIのオプションは `--help` で確認してから `config/models.yaml` に設定する。example 内の実CLIの例はテンプレートで、オプションは未確認。
- `sandbox: restricted`（任意コード実行・ファイル編集を禁止できていることを確認済み）にしたモデルだけが大会に参加できる。
- mock 以外のモデルを呼ぶ前に、対象と呼び出し回数の目安を表示して確認を求める（`--yes` で省略）。
- APIキーは設定ファイルに書かず、環境変数か各CLIのログイン状態を使う。ログ中のキーらしき文字列はマスクする。

## 制限事項
- 実AI CLIとの接続は未検証。
- 盤面はプロンプトに埋め込んで渡す方式のみ。CLIのファイル参照を使う方式は未実装。
- 対局は直列実行のみ。
- 費用・トークンはCLIがJSONで返した値のみ記録する。費用の上限は保証しない。
- `statistics.py` は Python 標準ライブラリの `statistics` と同名のため、このリポジトリから標準の `statistics` は import できない。

## ライセンス
未設定。
