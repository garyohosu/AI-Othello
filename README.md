# AI-Othello

Pythonを審判役として、CLIから起動する複数のAIモデル同士をオセロで対戦させる比較ツール。

[必須仕様・Claude Code実装指示書（RequiredSpecifications.md）](./RequiredSpecifications.md)

## 目標
- ChatGPT/Codex、Claude、Gemini、Grokなどのモデルを設定によって追加
- `●` `〇` `□` の8×8テキスト盤面を読み、各AIが座標または `PASS` を返す
- Pythonが合法手判定・反転・終局・反則を一元管理
- 全モデル総当たり、黒白交換、勝敗・反則・応答時間をCSV集計
- AIの生回答と盤面を保存し、後から誤回答を検証できる

## 反則（確定）
違法な着手、形式不正、打てる手があるときのPASSは反則。盤面を変えず同じ手番で再試行する。**1局で同じAIの反則が累積10回になったら反則負け。** 無限ループ防止のためであり、合法着手を挟んでもリセットしない。CLI起動エラーなどは別扱い。

## 開発状況
現時点では**仕様書と開発指示書のみ**。Pythonプログラムは未実装、テストは未実行。実行方法は実装完了後に追加する。

## Claude Codeで開発を開始する
リポジトリをクローンしてClaude Codeを起動し、次を指示する。

> RequiredSpecifications.mdを正本としてPythonのAIオセロ対戦ツールを実装して。まずオセロルールエンジンとpytestのテストを作り、次にモックCLIで対局・反則10回・総当たり・CSV集計・再開を実装して。実CLIは利用可能なコマンドと費用を確認してから接続して。実際に走らせたテストと未実施テストを分けて報告して。

```powershell
git clone https://github.com/garyohosu/AI-Othello.git
cd AI-Othello
claude
```

## ライセンス
未設定。
