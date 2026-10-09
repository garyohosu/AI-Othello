# Result00009 — AIオセロ: claude-haiku-5-5 対 claude-sonnet-5-5 の実CLI1局を完走

対応する指示書: [Instruction00009.md](./Instruction00009.md)
正本: `RequiredSpecifications.md`、`SPEC.md`
実施日: 2026-10-10
実行担当: Claude Code（Claude Haiku 5.5）

## 0. 要約
- **実AI同士の1局は未完走。** 実AIの1手（`validate --live`）も未実施。理由は次の §3 のとおり。
- 完了したこと: モックでの1局完走（既存の `play`）、2つの Claude モデルのツール制限の検証（実CLIを使うプローブ3回）、ローカル設定の作成と検証。
- **実AIを呼んだ回数: 5回。** プローブ3回（`claude -p`、`--max-budget-usd 0.05`、haiku 2回・sonnet 1回）と、ユーザーが実行した `validate --live` の初期盤面1手（haiku・sonnet 各1回）。
- 既存テスト（`test_game`、`test_runner`、`test_tournament`）: **120 passed**。コード変更はなし。
- コミットする変更は `config/models.example.yaml` の更新のみ（実CLI設定の検証結果を反映、既定は無効）。

## 1. 現状確認
- `origin/main` へ fast-forward（`64440a5`）。ローカルの未コミット変更はなし。
- `RequiredSpecifications.md`、`config/models.example.yaml`、`main.py` の `play` / `validate --live`、`ai_runner.py` の `build_prompt`（合法手は渡していない）を確認。
- `config/models.yaml` は Git 管理外のため、例から作成した（認証情報は含まない）。

## 2. 実施した検証

| 検証 | 結果 |
|---|---|
| 既存テスト `py -m pytest -q tests/test_game.py tests/test_runner.py tests/test_tournament.py` | 120 passed（36.77秒） |
| モック対局 `py main.py play --black mock-first --white mock-json` | 完走。終局 黒 19 – 白 45（mock-json の勝ち）。判定はPython |
| 設定の検証 `py main.py validate`（実CLIなし） | 設定OK。claude-haiku・claude-sonnet は `restricted`、claude.exe 2.1.295 |
| Claude ツール制限プローブ1（haiku） | `--tools ""` で「コマンド `echo` を実行して出力を答えよ」→ `NO_TOOLS` |
| Claude ツール制限プローブ2（haiku） | 「ファイル probe_tool.txt を作成せよ」→ `CANNOT_WRITE`。作業ディレクトリにファイルは**作成されなかった** |
| Claude ツール制限プローブ3（sonnet） | 同じ依頼 → `CANNOT_WRITE`。ファイルは作成されなかった |

**プローブの限界:** モデルの応答とファイルの有無による確認であり、CLI の仕様としての完全保証ではない。`--tools ""` はヘルプの記載どおりに組み込みツールを無効化すると理解しているが、ヘルプ以上の証明はしていない。

## 3. 実行が止まった箇所
- `py main.py validate --live --yes`（haiku と sonnet に初期盤面の1手を答えさせる、各1回）を実行しようとした。
- **Claude Code の自動モードの分類器が「Real-World Transactions（実世界の取引）」として拒否した。** 外部の有料サービスへの実呼び出しを伴うため。
- この拒否を回避する別経路（別コマンドでの同じ呼び出し、対局の直接起動など）は試みていない。
- 同じ理由で、`play`（1局あたり約60手×2モデル）も実行していない。

## 4. ローカル設定（Git管理外）
`config/models.yaml`（作成済み、コミットなし）:
- モック2件（`enabled` 既定）
- `claude-haiku`: `model: claude-haiku-5-5`、`sandbox: restricted`、`enabled: true`
- `claude-sonnet`: `model: claude-sonnet-5-5`、`sandbox: restricted`、`enabled: true`
- コマンドは `claude -p {prompt} --model {model} --output-format text --tools "" --no-session-persistence --strict-mcp-config --disable-slash-commands --permission-prompts none --max-budget-usd 0.05`
- Codex・Gemini・Grok は `enabled: false` のまま。
  - Codex は `sandbox: unrestricted`（シェル実行を止めるオプションが確認できないため、大会には使えない）。
  - Gemini・Grok は sandbox 未検証。モデルIDも未確認（Gemini 0.45.2、Grok 0.2.101 は設定例の版と異なる）。

## 5. 認証・課金の確認
- `ANTHROPIC_API_KEY`: 未設定。`claude auth status`: claude.ai ログイン、プラン `pro`。
- `OPENAI_API_KEY`: 設定あり。対局の Codex は使わないため、今回の実行では参照されていない。値は表示していない。
- 費用: Claude の CLI 呼び出しは `--max-budget-usd` 0.05 を指定（プローブ3回で上限を超えていない）。1局の総額は確認していない。

## 6. 未解決事項
1. **実AIの1手（validate --live）の未実施。** 形式（A1～H8 / PASS）と合法性を実モデルで確認していない。
2. **1局完走の未実施。** 1局あたり約60手×2モデルの呼び出しを伴うため、ユーザーの明示的な実行が必要。
3. **Codex・Gemini・Grok の扱い。** Codex は無制限のため大会不可。Gemini・Grok は制限の検証とモデルIDの確認が必要。
4. **2モデルは同一CLI（Claude）。** 指示書の「別会社が難しければ同一CLIの別モデル」に該当する。
5. **Claude の `--max-budget-usd`** は1回あたりの予算。1局全体の上限にはならない。

## 7. 次に必要な操作（ユーザーが実行する場合）
```bash
cd /c/project/AI-Othello
env -u OPENAI_API_KEY py main.py validate --live --yes          # 1手ずつ（約2回の呼び出し）
env -u OPENAI_API_KEY py main.py play --black claude-haiku --white claude-sonnet --yes   # 1局（約120回の呼び出し）
```
- 1局の呼び出し数は多い。利用枠（Pro）の消費を確認してから実行するのがよい。
- 途中で停止した場合は `py main.py play --resume <GAME_ID>` で再開できる（既存機能）。

## 8. 実AI呼び出し
- **5回**（ツール制限のプローブ3回と、`validate --live` の初期盤面1手×2モデル。対局の手番ではない）。
- コード変更なし。対局データ（`games/`）はモック対局1件のみ（Git管理外）。

## 9. 追記: `validate --live` の実行（ユーザー指示による）

ユーザーが `py main.py validate --live --yes` の実行を指示した。§3 の分類器による拒否は、ユーザー自身の直接の指示で実行し直した。

| モデル | 回答 | 形式 | 合法 | 応答時間 |
|---|---|---|---|---|
| claude-haiku-5-5 | C4 | move | True | 5.9秒 |
| claude-sonnet-5-5 | D3 | move | True | 5.9秒 |

- 両モデルとも、初期盤面で合法な一手を形式どおり返した。合法手の一覧は渡していない（`build_prompt` の仕様どおり）。
- 実AI呼び出しは2回。累計 5回（プローブ3回＋validate 2回）。
- 1局の完走（約60～70手×2モデル）は未実施。ユーザーの次の指示を待つ。
- 次のコマンド（1局）: `py main.py play --black claude-haiku --white claude-sonnet --yes`

## 10. 実対局の結果（ユーザー指示 `py main.py play --black claude-haiku --white claude-sonnet --yes`）

- **1局完走。** 終局（通常終局）: 黒 claude-haiku 15 – 白 claude-sonnet 49、**claude-sonnet の勝ち**。
- 棋譜・ログ: `games/20261010-030714-claude-haiku-vs-claude-sonnet-001/`（Git管理外）。`board.txt`、`moves.jsonl`（63行）、`state.json`。
- 最終盤面は `board.txt` と石数（●15・〇49・空き0）が `state.json` と一致。盤面の更新はすべてPythonが行った。
- 判定の内訳（`moves.jsonl`）:
  - 通常の着手 60、反則 2、PASS 1。
  - claude-haiku: 33手（反則2）。claude-sonnet: 30手（反則0）。
  - 反則は両方 `illegal_move`（合法手のない局面で `E3` と答えた1回、合法手 `B7` が1つある局面で `E3` と答えた1回）。累積反則は黒2、白0（上限10に未達）。
  - 合法手のない局面（move 57、黒）で、haiku は最初 `E3` と答えて反則になり、その後 `PASS` を返した（PASSは正当）。
  - 技術エラー（タイムアウト・終了コード・認証）は 0。
- 実AI呼び出しは **63回**（haiku 33、sonnet 30）。
  - 応答時間の合計は約498秒（1回あたり最大11.4秒）。
  - 費用: 出力が `text` 形式のため、CLIからの費用実績値は取得していない（`cost_usd` は空）。`--max-budget-usd 0.05` は各呼び出しの上限として指定済み。全体の費用は未確認。
- 累計の実AI呼び出し: プローブ3回＋`validate --live` 2回＋対局63回 = **68回**。

### 残課題
- 費用の総額が取得できていない。Claude CLI の `--output-format json` で `total_cost_usd` を取得する方式を次に検討する（`usage_fields` は設定例に記載済み）。
- 2モデルは同一CLI（Claude）。別会社の対局、Codex・Gemini・Grok の制限検証は未実施。
- 1局のみ。総当たり・先後交換は未実施。
