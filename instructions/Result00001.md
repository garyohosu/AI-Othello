# 作業結果 00001 — Q&A確定内容の仕様反映と実装開始

対応する指示書: [Instruction00001.md](./Instruction00001.md)
実施日: 2026-10-08
実行担当: Claude Code（Claude Opus 5.5）

## 1. 結論
- 指示書の作業内容1〜6はすべて実施した。
- QandA.md の22項目を SPEC.md（v0.2）に反映し、QandA.md の各項目を「反映済」にした。
- ルールエンジン（作業内容3）と、モックCLIを使う対局管理一式（作業内容4）を実装した。
- pytest は 108件すべて成功した。
- 実AI CLI（Claude Code / Codex / Gemini / Grok）は一度も呼び出していない。課金の発生する操作もしていない。

## 2. 実施内容

### 2.1 仕様の反映（SPEC.md v0.2）
- 反則: プレイヤーごと・1局で累積10回に達したら即反則負け。目的は無限ループの防止であり、合法手を打ってもリセットしないことを明記した（4.3節）。
- QandA の回答を次のとおり反映した（暫定案から変わった項目に★）。

| Q | 反映内容 |
|---|---|
| Q-01 | board.txt はLF改行、最終行にも改行。読み込みは最終改行なしも許容 |
| Q-02 | プロンプトテンプレート（凡例・担当色・座標規則）を確定。色の部分だけを切り替える |
| Q-03 | タイムアウト既定120秒、モデル別に上書き可 |
| Q-04 | 合法手がなくてもAIを呼びPASSを回答させる。自動PASSは将来の任意機能 |
| Q-05 | 大文字のみ。`d3`・`pass`・説明付きは形式反則 |
| Q-06 | 正常終了で本文が空なら形式反則 |
| Q-07 | `I9`・`A0`・`Z99` などは形式反則。A1〜H8 で着手不可のものだけ違法座標 |
| Q-08 | 再試行は同一プロンプト。反則内容やヒントは渡さない |
| Q-09 | 構造化出力が壊れていたら `parse` 技術エラー |
| ★Q-10 | 1→2→4秒の指数バックオフ（上限30秒）。Retry-After 相当があれば優先 |
| ★Q-11 | 反則負けの対局は石差集計から除外（生データは記録） |
| Q-12 | 自己対戦は除外 |
| ★Q-13 | validate は課金なし。`--live` 指定時のみ1手の疎通確認 |
| Q-14 | 直列実行 |
| ★Q-15 | `games/` と `results/` を .gitignore。公開用は `reports/` などに手動コピー |
| ★Q-16 | 技術中断は自動再実行しない。`--retry-aborted` で別IDの再対局 |
| ★Q-17 | 平均応答時間は回答本文を取得できた試行のみ。技術エラーは別指標 |
| Q-18 | 廉価モデル合計2種類で1局だけ試す |
| ★Q-19 | 実CLI実行前に対象・呼び出し回数の目安を表示し、明示的な確認を求める |
| ★Q-20 | Grok の公式CLIがなければ xAI API の最小ラッパーを作ってよい（未実装） |
| ★Q-21 | サンドボックス制限を確認できないCLIは大会から除外 |
| Q-22 | 初回+リトライ3回で1手番最大4試行。反則とは別カウンタ |

### 2.2 実装
| ファイル | 内容 |
|---|---|
| `game.py` | ルールエンジン（純粋関数）。`●〇□` の盤面入出力と検証、8方向反転、合法手、終局、勝者 |
| `ai_runner.py` | CLIアダプタ（`mock` / `cli`）。引数リストで起動（`shell=True` なし）、`shutil.which` で `.cmd` を解決、プロンプトは標準入力、タイムアウト時にプロセスツリーごと終了、回答の抽出と形式判定、秘密情報のマスク |
| `tournament.py` | 手番進行、反則（累積10回で反則負け）と技術エラー（手番ごと最大4試行で技術中断）、指数バックオフ、保存（state.json をコミット点とする）と再開時の照合、総当たり（黒白交換）、技術中断の再対局 |
| `statistics.py` | `results/matches.csv` と `results/ranking.csv` の集計、端末表示 |
| `main.py` | `play` / `tournament` / `results` / `list-models` / `validate`。実CLIの実行確認、サンドボックス未確認モデルの拒否 |
| `tests/mock_cli.py` | モックAI CLI（合法手・違法座標・PASS・形式違反・空回答・JSON・壊れたJSON・非ゼロ終了・認証エラー・遅延） |
| `tests/test_game.py` / `test_runner.py` / `test_tournament.py` | 自動テスト（計108件） |
| `config/models.example.yaml` / `config/rules.yaml` | 設定例（モックのみ有効）とルール |
| `pytest.ini` / `requirements.txt` / `.gitignore` | テスト設定、依存（PyYAML, pytest）、Git除外設定 |
| `SPEC.md` / `QandA.md` / `README.md` | 仕様反映、反映済みの記録、セットアップ・使い方・制限事項 |

## 3. 実際に実行したコマンドと結果

| コマンド | 結果 |
|---|---|
| `git pull`（ローカルの dream.md を stash して実行） | 成功（Instruction00001.md と QandA 回答を取得） |
| `py --version` | Python 3.14.0 |
| `py -c "import yaml,pytest"` | PyYAML 6.0.3、pytest 9.0.2 |
| `command -v claude codex gemini grok` | 4つともコマンドが存在することだけ確認。`--help` も実行していない |
| `py -m pytest -q tests/test_game.py` | 31 passed |
| `py -m pytest -q`（途中段階） | 2 failed / 103 passed → テスト側の期待値の誤り2件を修正（下記4.1） |
| `py -m pytest -q`（途中段階） | 1 failed / 105 passed（`test_resume_keeps_foul_count` が PermissionError。下記4.2） |
| `py -m pytest -q tests/test_tournament.py` を4回 | 4回とも 30 passed |
| `py -m pytest -q`（最終） | **108 passed**、216 warnings |
| `py main.py --config config/models.example.yaml tournament`（出力先はスクラッチパッド） | モック2モデルで2局完走、CSV出力を確認 |
| `py main.py validate`（models.yaml なし） | 終了コード2、作成を促すメッセージ |
| `py main.py --config config/models.example.yaml validate` / `list-models` | 成功 |
| `timeout 6 py main.py ... play --black slow --white fast` → `play --resume <id>` | 強制終了後に再開して終局。結果は中断なしの対局と同じ 19-45 |
| `timeout 15 py main.py ... tournament --models slow,fast,flaky` → `tournament --resume <id>` | 再開して6局を処理。flaky（常に非ゼロ終了）の4局は技術中断 |
| `tournament --resume <id> --retry-aborted`（flaky を正常なモックに差し替え） | 4局の再対局（`-r1`）を追加して完走。元の4局は技術中断のまま残る |

## 4. テストの成功・失敗・未実施

- 成功: 108件（`tests/test_game.py` 31件、`tests/test_runner.py` 45件、`tests/test_tournament.py` 32件）
- 失敗: 最終実行では0件
- 未実施: 実CLIを呼ぶテスト（`real_cli` マーカー）は作成していないし、実行もしていない

### 4.1 途中で失敗したテスト（テスト側の誤り）
- `test_tournament_csv`: 「a のトークン取得局数が4」を期待していたが、実際は3。c が黒の対局では c が初手から反則を続けて反則負けになり、a は一度も回答しないため。期待値を3に直した。
- `test_technical_errors_and_fouls_are_separate_counters`: 台本で同じ手番に技術エラーを4回入れており、仕様どおり技術中断になった。台本を直し、「反則を挟んでも手番内の技術エラー回数はリセットされない」テストを別に追加した。

### 4.2 一度だけ発生した PermissionError
- 全体実行の1回で `test_resume_keeps_foul_count` が PermissionError で失敗した。再実行では再現しなかった。
- トレースバックを保存していないため、原因は確定していない。Windows で `os.replace` の置換先をウイルス対策ソフト等が一時的に開いていたためと推定している。
- 対策として、`os.replace` を PermissionError 時に短い間隔で最大10回リトライする `replace_with_retry` を追加した。追加後の全体実行2回はどちらも成功した。

### 4.3 警告
- 216件の警告は、環境にグローバルに入っている `pytest_freezegun` プラグインが出す DeprecationWarning（distutils の LooseVersion）。本リポジトリのコード由来ではない。

## 5. 仕様間の矛盾・解釈
- Q-21 と正本: 正本は「CLIの制約で制限できない場合は記録する」。QandA の回答は「原則として実大会から除外する」。QandA の方が厳しいので QandA に従った。大会では `sandbox: restricted` 以外を拒否する。`play --allow-unrestricted` と `validate --live --allow-unrestricted` は検証用として許可し、制限できていない旨をログに記録する。
- 「盤外座標」: 正本は反則の一種として挙げている。成績の内訳は3分類なので、Q-07 の回答どおり形式違反に含めた。
- 上記以外に、正本・QandA・SPEC の間の矛盾は見つからなかった。

## 6. 未完了事項・制限
- 実AI CLIとの接続: 未着手。汎用アダプタ（`provider: cli`）は実CLIで一度も動かしていない。各CLIのオプションは未確認。
- Grok 用の xAI API ラッパー（Q-20）: 未実装。
- 汎用アダプタは Retry-After 相当の値を取り出さない（`retry_after_sec` は常に未設定で、指数バックオフだけが働く）。
- `board_delivery: file`（CLIの読取専用ファイル参照）: 未実装。インライン方式のみ。
- 合法手がないときの自動PASSオプション（Q-04 の将来機能）: 未実装。
- 対局の並列実行: 未実装（Q-14 により直列のみ）。

## 7. 問題点・気づき
- `statistics.py` は Python 標準ライブラリの `statistics` と同名で、リポジトリ内からは標準の `statistics` を import できない。正本のファイル名に従ったが、必要になれば改名を検討する。
- `timeout` コマンドで本体を強制終了したとき、子プロセス（モックCLI）が先に落ち、その試行が技術エラー（nonzero_exit）として1件記録された。Ctrl+C の場合は子プロセスを別プロセスグループで起動しているので KeyboardInterrupt 側で破棄される想定だが、実際の Ctrl+C 操作では確認していない。
- この環境の `python` コマンドは Microsoft Store のスタブで、実行しても何もしない。`py` を使う必要がある（README に記載）。
- Git の `core.autocrlf=true` のため、コミット時に LF→CRLF の警告が出る。

## 8. 次の作業候補
1. 実CLIを1つ選び（例: Claude Code CLI）、`--help` でプロンプトの標準入力、モデル指定、構造化出力、ツール実行・ファイル編集の禁止方法を確認し、`config/models.yaml` を作る。
2. サンドボックス制限を確認できたら `sandbox: restricted` にし、ユーザーの許可を得てから `validate --live` で1手だけ疎通確認する。
3. Q-18 に従い、廉価モデル合計2種類で1局だけ対局し、費用を記録する（要ユーザー許可）。
4. 汎用アダプタで Retry-After 相当を取り出せるかを、実CLIの出力を見て判断する。
5. 必要なら `.gitattributes` で改行コードを統一する。

## 9. コミット・プッシュ
- 実装コミット: `ca0b741`（`main` に push 済み。`d3700f0..ca0b741`）
- 本ファイルと dream.md は、上記の後の別コミットで push する。
