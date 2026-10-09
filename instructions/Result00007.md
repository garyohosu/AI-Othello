# Result00007 — 監督ランナー（事前登録キューを1回の起動で順に実行する最小版）

対応する指示書: [Instruction00007.md](./Instruction00007.md)
前回結果: [Result00006.md](./Result00006.md)（コミット `e1aad35`）
実施日: 2026-10-10
実行担当: Claude Code（Claude Haiku 5.5）
作業環境: Windows 11 Pro 10.0.26300 / Python 3.13（`py`）

## 0. 要約
- **完了。** 事前に登録した指示書キューを1回の起動で順に処理する監督ランナーを実装した。成功したタスクは限定的に commit でき、commit・push は既定で無効。
- **実AI呼び出し: 0回。** `claude` / `codex` は起動していない（CLIのヘルプ・バージョンも実行していない）。
- テスト: devloop 既存 **62 passed**（変更なし）、監督ランナーの新規 **18 passed**、全体 **200 passed**。失敗0、skip 0。
- dry-run: 副作用なし（`.devloop/` 作成なし、Git変更なし、AI起動なし）。
- 未検証: 実CLIでの動作、金額上限（保証できない）、Windowsでの作業ディレクトリ外書き込みの遮断。

## 1. 設計

### 1.1 構成（新規・変更ファイル）

| ファイル | 種別 | 役割 |
|---|---|---|
| `tools/devloop/autopilot.py` | 新規 | 監督ランナー本体。キュー読込・検証、タスクの順次実行、commit / push の判断、状態保存・再開、CLI |
| `tools/devloop/gitwrite.py` | 新規 | 監督ランナー専用の限定された Git 書き込み（パス指定の stage、commit、push、trailer 検索）。保護ブランチを拒否 |
| `tools/devloop/queue.example.yaml` | 新規 | キュー設定例（既定は安全側） |
| `tests/test_autopilot.py` | 新規 | 監督ランナーのモックテスト18件 |
| `tools/devloop/controller.py` | 変更（小） | `Outcome.calls`（この実行の AI 呼び出し数）を追加。新規状態に `start_instruction`（最初の指示書）を記録 |
| `tools/devloop/gitutil.py` | 変更（小） | 読み取り専用の許可に `log` を追加（commit の再開判定用）。Controller 本体は引き続き書き込みをしない |
| `docs/devloop.md` | 変更 | 「監督ランナー」の節（使い方・停止条件・保証しないこと） |

Controller の安全判定（機械的チェック、禁止変更、番号衝突、レビュー形式、上限）は変更していない。

### 1.2 実行の流れ
1. 起動時: 設定が dry_run でないこと、`require_clean_worktree: true`、実AIなら承認（`allow_real_cli` と `--allow-real`）、キューの指示書が存在すること、番号の区画が重ならないこと（次の番号 ≥ 前の番号 + `max_loops`）、既存の状態がないこと（新規開始時）。
2. タスクごと: 子の Controller を実行（残りの呼び出し枠だけを渡す）。`complete` かつ機械的テスト成功かつ禁止変更なしのときだけ次の段階へ。それ以外は即停止。
3. commit 段階: 現在のブランチが保護ブランチ（`main` / `master` / detached）でないこと、ブランチが開始時と同じであること。`git status` の変更を列挙し、禁止変更がないこと、結果報告が変更に含まれること、パスが安全であることを確認してから `git add -- <paths>` で stage。stage 結果が想定と一致した場合だけ commit。メッセージに `Devloop-Instruction: <指示書>` を入れる。
4. push 段階（有効な場合のみ）: `origin` の作業ブランチへ `refs/heads/<b>:refs/heads/<b>`（強制なし）。
5. 状態は `.devloop/autopilot.json` に保存（各タスクの状態、commit SHA、呼び出し回数、経過時間、総呼び出し数）。

### 1.3 安全上の判断（指示書の要件に対する判断）
- **main / master への commit も拒否**した。指示書は main への自動 push を禁じており、commit も同様に扱うのが安全側と判断した。使い捨てクローンの作業ブランチで使う前提。
- **commit と push は二重承認**: キュー（`allow_commit` / `allow_push`）と CLI（`--commit` / `--push`）の両方が必要。`allow_push` は `allow_commit` を前提とする（設定時にエラー）。
- **commit できなかったタスクの後は進まない。** commit 無効のまま完了した場合は `commit_disabled` で停止し、作業ツリーに変更を残す（次のタスクの混入を防ぐ）。
- **push はタスクごと。** commit のたびに push する（失敗したら即停止）。
- **番号の区画**: retry が使う `N+1 … N+max_loops-1` を次のタスクに使わせない。`max_loops` が既定の3なら、タスク番号は3ずつ空ける必要がある（例: 10, 13）。
- **時間上限はタスクの区切りで判定**する。1回のAI呼び出しは既存のタイムアウト（実装1800秒、レビュー600秒）で止まる。
- **呼び出し回数**: 子の Controller の `max_total_calls` は累積値として扱い、再開時は「そのタスクの既使用分 + 全体の残り」を上限にした。
- **再開時の二重実行・二重 commit 防止**: 完了済みタスクは再実行しない。子の状態が完了・停止済みならその結果を使う。commit は、変更がなく `Devloop-Instruction:` の trailer を持つ commit が既にあれば記録だけする。ブランチが変わっていれば再開しない。
- **状態がある状態での新規開始は拒否**（上書きしない）。
- AI の報告文だけでは成功にしない。`history[-1].checks.tests_passed` と禁止変更を確認してから完了とする。

## 2. 実行したテストと結果

| コマンド | 結果 |
|---|---|
| `py -m pytest -q tests/test_autopilot.py` | **18 passed**（26.06秒） |
| `py -m pytest -q tests/test_devloop.py` | **62 passed**（41.53秒）— 既存の devloop テストは退行なし |
| `py -m pytest -q`（全体） | **200 passed**（107.65秒）、失敗0、skip 0 |

監督ランナーのテスト18件（すべて実AIなし、Gitは一時リポジトリとローカル bare リモートだけ）:

| 要件 | テスト |
|---|---|
| 2件のタスクが1回の起動で順に complete → commit | `test_two_tasks_complete_and_each_is_committed` |
| retry → 修正 → complete、番号が次の項目と衝突しない | `test_retry_instruction_is_committed_with_its_task` |
| blocked で後続タスクを開始しない | `test_blocked_stops_before_next_task` |
| テスト失敗の complete は commit しない | `test_complete_with_failing_tests_is_not_committed` |
| 禁止変更で停止し commit しない | `test_forbidden_change_stops_without_commit` |
| 総AI呼び出し上限で後続を開始しない | `test_call_budget_stops_before_next_task` |
| commit 無効で停止 → 再開時は完了タスクを再実行せず commit | `test_commit_disabled_stops_and_resume_commits_without_rerunning` |
| 再実行で二重実行・二重 commit をしない | `test_rerun_does_not_duplicate_work_or_commits` |
| 状態がある状態での新規開始を拒否 | `test_fresh_start_refused_when_state_exists` |
| 保護ブランチへ commit しない | `test_protected_branch_is_never_committed` |
| 作業ブランチだけを bare リモートへ push（強制なし） | `test_push_to_work_branch_on_local_bare_remote` |
| push は queue と CLI の両方が必要 | `test_push_requires_flag_and_queue_permission` |
| gitwrite が main/master の push・commit、`../` や `-A` の stage を拒否 | `test_gitwrite_refuses_protected_branch_and_unsafe_paths` |
| 番号の区画の重なり・キュー項目の不正を拒否 | `test_numbering_overlap_is_rejected`、`test_queue_limits_and_unknown_keys_are_rejected` |
| 作業ツリーが汚れていれば開始しない | `test_dirty_worktree_refused_at_start` |
| dry-run は副作用ゼロ、dry_run 設定では実行しない | `test_dry_run_has_no_side_effects` |
| 実AIの承認がなければ1件も始めない | `test_real_ai_without_approval_stops_before_any_task` |

## 3. dry-run の実測
- コマンド（一時キュー、リポジトリ外の設定）: `py -m tools.devloop.autopilot --repo . --queue <一時キュー> --config <一時設定> --dry-run`
- 結果: 計画を表示（キュー1件、上限12回・3600秒、commit 無効、push 無効）。Controller の計画表示（AI起動なし）。終了コード 0。`.devloop/` は作成されず、`git status` は Result00007 作成前と同じ変更のみ。
- `tools/devloop/queue.example.yaml` を指定すると、存在しない `Instruction00010.md` を検出して `設定エラー` で終了コード 2。想定どおりの安全停止。

## 4. 観測したGitの動作
- `git status --porcelain=v1 -z --untracked-files=all` の個別ファイル列挙を使い、ディレクトリ単位の stage をしない設計にした。
- 保護ブランチ・detached HEAD の検出は `git rev-parse --abbrev-ref HEAD` の結果で判定した。
- commit の trailer 検索は `git log -n300 --format=%H%x1f%B%x1e` で行った。
- push は一時の bare リモートに対してのみ実行した。実在のリモート（GitHub）へのテスト push はしていない。

## 5. 変更の範囲と注意
- Controller の判定ロジックは変更していない。追加したのは `Outcome.calls` と状態の `start_instruction` だけ。
- ランナーが作る commit には `Co-Authored-By` 行を付けていない（ランナーは Git を直接の作業者として扱わない）。この Result の作成に伴うコミットには、指示どおり `Co-Authored-By: Claude Haiku 5.5` を付けた。
- 監督ランナーの commit は、使い捨てクローンの作業ブランチでの利用を前提とする。このリポジトリの `main` で実行しない。

## 6. 未解決事項・保証しないこと
- **金額の上限は保証しない。** 呼び出し回数と時間の上限だけで、費用の総額は決まらない。Codex の CLI に金額上限のオプションは確認されていない（Result00005 から変更なし）。
- **実CLIの動作は未検証。** `claude -p` の標準入力受け付け、`codex exec` の出力取得、`acceptEdits` が作業ディレクトリ外への書き込みを防ぐか、`--max-budget-usd` の実効性。
- **時間上限はタスクの区切りでのみ判定**する。1回のAI呼び出し中の超過は、そのタスクのタイムアウトに任せる。
- **push の認証・ネットワーク失敗**は `push_failed` で停止するが、実リモートでの認証動作は未確認。
- **再開の判定は `.devloop` の状態と commit trailer に依存**する。`.devloop` を手で消すと、commit 済みの作業を再実行するおそれがある。状態ファイルは手で編集しない。
- 自動の製品仕様の追加・タスクの自動生成は対象外（指示どおり）。

## 7. 次に行う最小の実CLI試験（未実行・承認待ち）
1. 使い捨てクローンと作業ブランチ（例: `devloop-trial`）を用意する。元のリポジトリは変更しない。
2. 課題を1件だけ登録する（番号は `max_loops` を考慮して空ける。例: `Instruction00010.md`）。
3. 設定: `max_loops: 1`、`max_total_calls: 2`、`max_same_failure: 1`、`allow_real_cli: true`。キューは `max_total_calls: 2`、`allow_commit: true` にする場合のみ commit も試す。
4. `--dry-run` で表示を確認 → 承認を得て `--execute --allow-real`（commit を試すなら `--commit`）。
5. 完了後、`.devloop/autopilot.json` と `git log`、`git status`、`git diff` を確認し、Result に記録する。

**承認が必要な事項**: 実AIの起動（費用が発生し得る）、commit を試すかどうか、Claude の `--max-budget-usd` を付けるかどうか。

## 8. 実AI呼び出し
- 0回。`claude -p` / `codex exec` を一度も起動していない。テストはすべてモック（`tests/devloop_mocks/`）。
