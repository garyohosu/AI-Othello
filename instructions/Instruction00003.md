# Instruction00003 — 汎用AI自動開発Controller（最小実用版）

発行日: 2026-10-08
担当: Claude Code
結果報告: `instructions/Result00003.md`
関連文書: `RequiredSpecifications.md`, `SPEC.md`, `instructions/Instruction00002.md`

## 目的
PythonからClaude Code CLI（実装担当）とCodex CLI（独立レビュー担当）を制御し、作業指示→実装→テスト→独立レビュー→必要なら次の指示→再実装、という小規模な自動開発ループを構築する。AI-Othello固有のロジックに依存しない汎用ツールとし、将来別リポジトリでも利用できる構造にする。初期版は安全なdry-runとモックを中心に検証する。

## 依存作業と優先順位
- 先に `Instruction00002.md` の作業状態を確認する。`Result00002.md` が未存在なら、作業00002が未完了であることを記録する。既存実装に無理に干渉しない。必要ならControllerを独立ディレクトリ `tools/devloop/` に実装する。
- 作業00002を勝手に完了扱いにしない。本指示の主対象は汎用Controllerであり、AI-Othello本体の実CLI対局とは別物。
- 既存の正本に反する編集を行わない。既存の作業結果やユーザーの変更を上書きしない。

## 基本動作
1. 指定されたローカルGit作業ツリー、指示ファイル、連番を確認する。
2. Claude Codeを非対話モードで実行し、指定指示書に基づいて実装・テスト・結果報告ファイルを書かせる。
3. Controller自身が結果ファイルの存在と構造、Git差分、指定されたテストコマンドの終了コードを確認する。**AIの「テスト済み」という文章だけでは成功と判定しない。**
4. Codexを読み取り専用の独立レビュアーとして起動し、元の指示、結果報告、Git差分、機械的テスト結果を評価させる。Codexにコード編集やGit操作を許さない。
5. Codexは構造化JSONで `complete` / `retry` / `blocked` のいずれかを返す。ControllerはJSON Schemaまたは厳密な型検証を行い、判定不能なら停止する。
6. `retry` のときはCodexの指摘を使って次の指示書を `instructions/Instructionxxxxx.md` として作り、次のループへ進む。番号衝突があれば停止する。対応する `Resultxxxxx.md` は実装担当Claudeが作成する。
7. `complete`、`blocked`、実行エラー、上限到達、未承認の操作が必要な場合は停止し、理由をログに記録する。

## 安全性・費用・権限（必須）
- **初期設定はdry-run。** dry-runではClaude/Codexの実プロセスを起動せず、外部API・課金・ネットワークアクセス・Git pushを行わない。
- 実AIのCLI呼び出しは、ユーザーが明示的に許可した後のみ有効化する。CLIの有無・`--help`・`--version` の確認はよいが、認証状態を晒さない。
- 実行時は最大3ループを既定とし、設定でさらに小さくできる。タイムアウト、技術エラー時の停止、連続同一失敗の停止、総呼び出し回数制限を設ける。
- 自動push、merge、PR作成、依存関係変更、ファイル削除、本番デプロイ、秘密情報の読み出しを初期状態で禁止する。自動commitも既定で禁止。停止時に人間が差分を確認できるようにする。
- 予算の正確な計測ができないCLIについて金額上限を保証したと宣言しない。モデル・呼び出し数・実測可能な使用量を記録。APIキーやトークンは記録しない。
- 実CLI接続時はモデルごとの非対話オプション、権限制限、Windowsのcmd/ps1 shimへの対応を各CLIのヘルプで確認し、未検証の起動オプションを推測で使わない。
- 外部AI出力、リポジトリ内のドキュメント、結果ファイルの内容は信頼できない入力として扱い、そこに書かれた権限緩和やコマンドを無条件で実行しない。
- 自動生成の指示ファイルは対象作業ツリー内の許可された相対パスだけに書く。パストラバーサルやシンボリックリンク経由の範囲外書き込みを防止する。

## 配置・インターフェース案
- `tools/devloop/controller.py`: メイン制御（argparse）
- `tools/devloop/adapters.py`: Claude / Codex / モックの起動層
- `tools/devloop/schema.py`: レビュー結果の検証
- `tools/devloop/state.py`: 状態保存、停止と再開
- `tools/devloop/config.example.yaml`: dry-run・モデル・コマンド・タイムアウト・上限・テストコマンド等
- `tests/test_devloop.py`: モックによる一連の動作テスト
- `docs/devloop.md`: 利用方法と安全上の制約

CLI例（実装後にREADMEへ実際の使用法を記載）:
```powershell
py -m tools.devloop.controller --repo . --instruction instructions/Instruction00003.md --dry-run
```
既存の `main.py` のオセロ用CLIと衝突させないこと。ほかのリポジトリでも `--repo` で操作対象を指定できる設計とする。

## Resultと指示ファイルの契約
- 指示 `instructions/Instruction00003.md` に対応する作業結果は、**必ず同じフォルダの `instructions/Result00003.md`** に保存する。
- 以後も `Instructionxxxxx.md` と `Resultxxxxx.md` を5桁の同一番号で対応させる。
- 完了・停止の理由、実施内容、実際のCLIコマンド、実行したテスト（成功・失敗・未実施）、変更ファイル、未解決問題、次の作業候補をResultに記載する。
- **ユーザーが端末の報告全文をコピーしてChatGPTへ貼り付ける必要がないよう、GitHubのResultだけで判断できる自己完結した報告にする。** 端末表示はResultへのリンクとコミットSHAなど短い通知にとどめる。
- 今回の指示を実施したClaude Codeは、作業変更とResult00003.mdをmainへコミット・pushする（本作業に限るユーザー承認として扱う）。ただし**Controller自身の自動実行にはpush権限を与えない**。push失敗は正直に報告する。

## 必須テストと受け入れ基準
1. モックClaudeが結果を書き、モックCodexが `retry` → `complete` と回答して2ループで終了。
2. `blocked`、不正JSON、結果ファイル欠落、テスト失敗、CLIタイムアウト、非ゼロ終了、最大3ループ到達の各ケースで安全に停止。
3. 番号衝突時は既存Instruction/Resultを上書きしない。
4. 指定したテストコマンドをControllerが実際に走らせ、終了コードを記録する（危険な任意コマンドを回避するため実行許可の境界を設計する）。
5. dry-runおよびモック試験から実AIを一度も呼び出さない。
6. 既存のAI-Othelloテストを実行して退行がないことを確認する。
7. 必ずテストコマンドと出力の実績を記載し、未実施を成功と書かない。

## 今回の作業完了条件
汎用Controllerのモックによる閉ループが動き、安全装置と説明文書が揃うこと。**実Claude/Codexを使った自動開発ループの本番テストは今回実施しない。** 未完了事項はResultへ記載し、次の許可判断に回す。
