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
| 実AI CLI（Claude Code / Codex / Gemini / Grok） | **未接続・未検証**。CLIの存在・バージョン・`--help` だけを確認し、設定例を用意した。AIへの問い合わせは一度もしていない |

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
`config/models.example.yaml` で有効になっているのは、課金のないモックモデル（`mock-first`、`mock-json`）だけ。実CLIの設定例（`claude-cheap` など）はすべて `enabled: false` で、サンドボックス未確認のため対局には使えない。

```powershell
# 設定とCLIの存在・バージョンを確認（AIは呼ばない。実CLIには --version だけを実行）
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

## 実AI CLI の準備状況
2026-10-08 に、この環境で `where` / `--version` / `--help` だけを実行して確認した（[Result00002](./instructions/Result00002.md)）。

| CLI | バージョン | 非対話実行 | プロンプトの渡し方 | 判定 |
|---|---|---|---|---|
| Claude Code | 2.1.294 | `claude -p` | 引数（`claude.exe` なので可） | サンドボックス未検証 |
| Codex | codex-cli 0.161.0 | `codex exec` | 標準入力（`codex.cmd` なので引数は不可） | シェル実行を止められないため大会から除外 |
| Gemini | 0.50.0 | `gemini -p` | 標準入力（`gemini.cmd` なので引数は不可） | サンドボックス未検証 |
| Grok Build | 0.2.112 | `grok -p` | 引数（`grok.exe` なので可） | サンドボックス未検証 |

未確認の点:
- 廉価モデルの実際のモデルID（設定例は「未確認」のプレースホルダ）
- ツール無効化オプション（`--tools ""`、`--approval-mode plan` など）が実際に効くか
- 回答が標準出力にそのまま出るか、JSON 出力のフィールド名、トークン・費用の取り方

### 実CLIを呼ぶ前のチェックリスト（ユーザーの承認が必要）
実際のモデル呼び出しは課金が発生する可能性があるため、**ユーザーが明示的に承認するまで実行しない**。
1. 使うCLIとモデルIDを決め、`config/models.yaml`（Git 管理外）の `model` を実在するIDに書き換える。
2. サンドボックスの確認方法を決める。確認できるまで `sandbox` は `unknown` のままにする（勝手に `restricted` にしない）。Codex は現状のオプションでは除外。
3. 承認を得たら、まず `py main.py validate --live --allow-unrestricted` で1手だけ疎通確認する（実行前に対象と回数の確認が表示される）。
4. 結果を見てから、Q-18 の「廉価モデル合計2種類で1局」に進む。

### 共通の注意
- 各CLIのオプションは `--help` で確認してから `config/models.yaml` に設定する。
- `sandbox: restricted`（任意コード実行・ファイル編集を禁止できていることを確認済み）にしたモデルだけが大会に参加できる。
- mock 以外のモデルを呼ぶ前に、対象と呼び出し回数の目安を表示して確認を求める（`--yes` で省略）。
- APIキーは設定ファイルに書かず、環境変数か各CLIのログイン状態を使う。`env` に KEY / TOKEN / SECRET / PASSWORD を含む名前を書くと設定エラーになる。ログ中のキーらしき文字列はマスクする。
- 運用ログ（ファイル置換のリトライなど）は `games/_logs/ai-othello.log` に残る。

## 汎用AI自動開発ループ（tools/devloop）
オセロ本体とは別に、実装担当AI（Claude Code）と独立レビュー担当AI（Codex）を交互に動かして、指示書→実装→テスト→レビュー→次の指示書を最大3ループ回すコントローラを `tools/devloop/` に置いている。詳細は [docs/devloop.md](./docs/devloop.md)。

```powershell
# 計画の確認だけ（既定の dry-run。AIは起動しない）
py -m tools.devloop.controller --repo . --instruction instructions/Instruction00004.md --config tools/devloop/config.example.yaml
```
- 実行には設定の `dry_run: false` と `--execute`、実AIにはさらに `allow_real_cli: true` と `--allow-real` が必要。
- モックでの閉ループと安全装置はテスト済み。**実際の Claude Code / Codex でのループは未実施**（ユーザーの承認待ち）。
- コントローラは commit / push をしない。

## 制限事項
- 実AI CLIとの接続は未検証（AIへの問い合わせは未実施）。
- 盤面はプロンプトに埋め込んで渡す方式のみ。CLIのファイル参照を使う方式は未実装。
- 対局は直列実行のみ。
- 費用・トークンはCLIがJSONで返した値のみ記録する。費用の上限は保証しない。

## ライセンス
未設定。
