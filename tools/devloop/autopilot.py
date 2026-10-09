"""監督ランナー: 事前登録された作業キューを1回の起動で順に処理する。

- 1タスクの実行（実装→機械的チェック→レビュー→retry）は Controller に任せる。ここでは安全判定を緩めない。
- Controller が complete を返し、機械的テストが成功し、禁止変更がない場合に限り、限定的に commit する。
- commit / push は設定（queue の allow_commit / allow_push）と CLI（--commit / --push）の両方が必要。既定は無効。
- main / master への commit・push は拒否する。force push・merge・rebase・git add -A は使わない。
- 失敗・blocked・技術エラー・上限超過などでは即停止し、後続タスクを開始しない。
- 状態は .devloop/autopilot.json に保存し、--resume で二重実行・二重 commit せずに再開する。
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import gitutil, gitwrite
from .adapters import mask_secrets
from .controller import (
    EXIT_COMPLETE, EXIT_CONFIG, EXIT_INTERRUPTED, EXIT_STOPPED,
    Config, ConfigError, Controller, Outcome, load_config,
)
from .safety import SafetyError, classify_changes, instruction_number, result_rel, safe_repo_path
from .state import StateStore, _replace_with_retry, now_iso

MIN_CHILD_CALLS = 2  # 1タスクは実装1回+レビュー1回が最低
MAX_TASKS_HARD = 20
STATE_FILE = "autopilot.json"


# ---------------------------------------------------------------- キュー


@dataclass
class Queue:
    tasks: list[str]
    max_tasks: int = 5
    max_total_calls: int = 12
    max_elapsed_sec: float = 3600.0
    allow_commit: bool = False
    allow_push: bool = False

    @classmethod
    def from_dict(cls, data: Any, cfg: Config) -> "Queue":
        if not isinstance(data, dict):
            raise ConfigError("キューファイルの中身がオブジェクトではない")
        unknown = set(data) - set(cls.__dataclass_fields__)
        if unknown:
            raise ConfigError(f"未知のキュー項目: {sorted(unknown)}")
        tasks = data.get("tasks")
        if not isinstance(tasks, list) or not tasks or not all(isinstance(t, str) for t in tasks):
            raise ConfigError("tasks には指示書のパスを1つ以上、文字列の配列で書く")
        try:
            q = cls(**data)
        except TypeError as exc:
            raise ConfigError(f"キューの項目の型が不正: {exc}") from exc
        if not (1 <= q.max_tasks <= MAX_TASKS_HARD):
            raise ConfigError(f"max_tasks は1～{MAX_TASKS_HARD}")
        if len(tasks) > q.max_tasks:
            raise ConfigError(f"タスク数 {len(tasks)} が max_tasks {q.max_tasks} を超える")
        if len(set(tasks)) != len(tasks):
            raise ConfigError("同じ指示書が複数回登録されている")
        if q.max_total_calls < MIN_CHILD_CALLS:
            raise ConfigError(f"max_total_calls は{MIN_CHILD_CALLS}以上")
        if not q.max_elapsed_sec > 0:
            raise ConfigError("max_elapsed_sec は正の数")
        if q.allow_push and not q.allow_commit:
            raise ConfigError("allow_push は allow_commit と一緒に使う")
        numbers = []
        for t in tasks:
            try:
                numbers.append(instruction_number(t, cfg.instructions_dir))
            except SafetyError as exc:
                raise ConfigError(str(exc)) from exc
        for prev, nxt in zip(numbers, numbers[1:]):
            # 前のタスクの retry は prev+1 ... prev+max_loops-1 を使うため、次の番号はその先にする
            if nxt < prev + cfg.max_loops:
                raise ConfigError(
                    f"番号の区画が重なる: {prev} の次は {prev + cfg.max_loops} 以上にする（最大ループ {cfg.max_loops}）"
                )
        return q


def load_queue(path: str, cfg: Config) -> Queue:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if path.lower().endswith(".json"):
        data = json.loads(text)
    else:
        import yaml

        data = yaml.safe_load(text)
    return Queue.from_dict(data, cfg)


# ---------------------------------------------------------------- 結果


@dataclass
class RunResult:
    status: str  # complete / stopped / interrupted / dry_run
    reason: str
    detail: str = ""
    task: str = ""

    @property
    def exit_code(self) -> int:
        return {"complete": EXIT_COMPLETE, "dry_run": EXIT_COMPLETE, "interrupted": EXIT_INTERRUPTED}.get(
            self.status, EXIT_STOPPED)


def _outcome_from_state(child: dict[str, Any]) -> Outcome:
    return Outcome(child.get("status", "stopped"), child.get("reason", ""), child.get("detail", ""),
                   child.get("loop", 0), child.get("current_instruction", ""), child.get("history", []),
                   calls=child.get("calls", 0))


# ---------------------------------------------------------------- ランナー


class Runner:
    def __init__(
        self,
        cfg: Config,
        queue: Queue,
        repo: str,
        allow_real: bool = False,
        commit: bool = False,
        push: bool = False,
        out: Callable[[str], None] = print,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.cfg = cfg
        self.queue = queue
        self.repo = os.path.realpath(repo)
        self.allow_real = allow_real
        self.commit_enabled = queue.allow_commit and commit
        self.push_enabled = queue.allow_push and push and self.commit_enabled
        self.out = out
        self.clock = clock
        self.store = StateStore(self.repo, cfg.state_dir)
        self.state_prefix = cfg.state_dir.strip("/").replace("\\", "/") + "/"
        self.state_path = os.path.join(self.store.dir, STATE_FILE)
        self._t0 = clock()

    # ------------------------------------------------ 共通

    def _check_repo(self) -> None:
        Controller(self.cfg, self.repo, out=self.out)._check_repo()

    def _user_changes(self) -> list[str]:
        return [p for _, p in gitutil.status_entries(self.repo)
                if not p.replace("\\", "/").startswith(self.state_prefix)]

    def _load_state(self) -> dict[str, Any] | None:
        if not os.path.exists(self.state_path):
            return None
        with open(self.state_path, encoding="utf-8") as f:
            return json.load(f)

    def _save(self, state: dict[str, Any]) -> None:
        self.store.ensure_dir()
        state["updated_at"] = now_iso()
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        _replace_with_retry(tmp, self.state_path)

    def _elapsed(self, state: dict[str, Any]) -> float:
        return state.get("elapsed_sec", 0.0) + (self.clock() - self._t0)

    def _child_store_state(self, instruction: str) -> dict[str, Any] | None:
        child = self.store.load()
        if child and child.get("start_instruction") == instruction:
            return child
        return None

    # ------------------------------------------------ 計画（副作用なし）

    def plan(self) -> RunResult:
        self._check_repo()
        self.out("[dry-run] AIの起動・ファイルの書き込み・Git変更はしない")
        self.out(f"リポジトリ: {self.repo}")
        self.out(f"キュー: {len(self.queue.tasks)}件（上限 {self.queue.max_tasks}件）")
        self.out(f"上限: 総AI呼び出し {self.queue.max_total_calls}回、経過 {self.queue.max_elapsed_sec}秒、"
                 f"タスクあたりループ {self.cfg.max_loops}回")
        self.out(f"commit: {'有効' if self.commit_enabled else '無効'}（queue.allow_commit と --commit の両方が必要）")
        self.out(f"push: {'有効（作業ブランチのみ）' if self.push_enabled else '無効'}"
                 "（queue.allow_push と --push と commit の有効化が必要）")
        for t in self.queue.tasks:
            Controller(self.cfg, self.repo, allow_real=self.allow_real, out=self.out).plan(t)
        return RunResult("dry_run", "dry_run")

    # ------------------------------------------------ 実行

    def run(self, resume: bool = False) -> RunResult:
        self._check_repo()
        if self.cfg.dry_run:
            raise ConfigError("設定が dry_run: true のため実行できない（--dry-run で計画を確認する）")
        if not self.cfg.require_clean_worktree:
            raise ConfigError("監督ランナーは require_clean_worktree: true が必須")
        if self.cfg.uses_real_ai and not (self.cfg.allow_real_cli and self.allow_real):
            return RunResult("stopped", "approval_required",
                             "実AIのCLIを使う設定だが、allow_real_cli: true と --allow-real の両方による許可がない")
        ctrl = Controller(self.cfg, self.repo, allow_real=self.allow_real, out=self.out)
        for t in self.queue.tasks:
            ctrl._check_instruction(t)

        state = self._load_state()
        if resume:
            if state is None:
                raise ConfigError("再開できる監督ランナーの状態がない（.devloop/autopilot.json）")
            if state["status"] == "complete":
                self.out("[complete] 既に完了している（二重実行しない）")
                return RunResult("complete", "complete")
            if state["order"] != self.queue.tasks:
                raise ConfigError("キューがこの状態を作ったときと違う。キューを変えずに再開する")
            if gitutil.head(self.repo) is None:
                raise ConfigError("HEAD がない")
            if state["branch"] != gitwrite.current_branch(self.repo):
                raise ConfigError(f"ブランチが変わっている（開始時: {state['branch']}）。再開しない")
            state["status"] = "running"
            self.store.log("autopilot_resume", tasks=len(self.queue.tasks))
        else:
            if state is not None:
                raise ConfigError(
                    f"監督ランナーの状態がある（status: {state['status']}）。--resume で再開するか、"
                    ".devloop/autopilot.json を確認する（上書きしない）"
                )
            dirty = self._user_changes()
            if dirty:
                return RunResult("stopped", "dirty_worktree", f"未コミットの変更がある（上書き防止）: {dirty[:10]}")
            state = {
                "status": "running",
                "started_at": now_iso(),
                "repo": self.repo,
                "branch": gitwrite.current_branch(self.repo),
                "start_head": gitutil.head(self.repo),
                "order": list(self.queue.tasks),
                "commit_enabled": self.commit_enabled,
                "push_enabled": self.push_enabled,
                "total_calls": 0,
                "elapsed_sec": 0.0,
                "tasks": {t: {"status": "pending", "number": instruction_number(t, self.cfg.instructions_dir)}
                          for t in self.queue.tasks},
            }
            self.store.log("autopilot_start", tasks=self.queue.tasks)
        self._save(state)

        result = RunResult("complete", "complete")
        try:
            for t in self.queue.tasks:
                rec = state["tasks"][t]
                if rec["status"] in ("committed", "skipped"):
                    continue
                stop = self._run_task(state, t, rec)
                if stop is not None:
                    result = stop
                    break
        except KeyboardInterrupt:
            result = RunResult("interrupted", "interrupted", "Ctrl+C で中断した。--resume で再開できる")
        return self._finish(state, result)

    def _finish(self, state: dict[str, Any], result: RunResult) -> RunResult:
        state["elapsed_sec"] = self._elapsed(state)
        self._t0 = self.clock()
        state["total_calls"] = sum(r.get("calls", 0) for r in state["tasks"].values())
        state["status"] = result.status if result.status != "dry_run" else state["status"]
        state["reason"] = result.reason
        state["detail"] = result.detail
        state["finished_at"] = now_iso()
        self._save(state)
        self.store.log("autopilot_finish", status=result.status, reason=result.reason, task=result.task)
        self.out(f"[{result.status}] {result.reason}: {result.detail}".rstrip(": "))
        self.out(self._summary(state))
        return result

    def _summary(self, state: dict[str, Any]) -> str:
        lines = ["作業サマリー:"]
        for t in state["order"]:
            r = state["tasks"][t]
            extra = f" commit={r['commit'][:10]}" if r.get("commit") else ""
            lines.append(f"  - {t}: {r['status']}（AI呼び出し {r.get('calls', 0)}回）{extra}")
        lines.append(f"合計AI呼び出し: {state['total_calls']}/{self.queue.max_total_calls}")
        return "\n".join(lines)

    def _stop(self, state: dict[str, Any], task: str, reason: str, detail: str = "") -> RunResult:
        return RunResult("stopped", reason, detail, task)

    # ------------------------------------------------ 1タスク

    def _run_task(self, state: dict[str, Any], t: str, rec: dict[str, Any]) -> RunResult | None:
        if rec["status"] != "complete":
            if self._elapsed(state) > self.queue.max_elapsed_sec:
                return self._stop(state, t, "max_elapsed", f"経過時間が上限 {self.queue.max_elapsed_sec}秒に達した")
            remaining = self.queue.max_total_calls - sum(r.get("calls", 0) for r in state["tasks"].values())
            if remaining < MIN_CHILD_CALLS:
                return self._stop(state, t, "max_total_calls",
                                  f"総AI呼び出しが上限 {self.queue.max_total_calls} 回に近い（残り {remaining}）")
            outcome = self._run_child(state, t, rec, remaining)
            if isinstance(outcome, RunResult):
                return outcome
            if outcome.status == "interrupted":
                rec["status"] = "interrupted"
                self._save(state)
                return RunResult("interrupted", "interrupted", outcome.detail, t)
            if outcome.status != "complete":
                rec["status"] = "stopped"
                rec["reason"] = outcome.reason
                self._save(state)
                return self._stop(state, t, outcome.reason, outcome.detail)
            last = outcome.history[-1] if outcome.history else {}
            checks = last.get("checks", {})
            if not checks.get("tests_passed") or checks.get("forbidden"):
                rec["status"] = "stopped"
                self._save(state)
                return self._stop(state, t, "inconsistent_complete",
                                  "complete だが機械的テストの失敗または禁止変更がある（commit しない）")
            rec["status"] = "complete"
            rec["loops"] = outcome.loops
            self._save(state)
            self.store.log("autopilot_task_complete", task=t, loops=outcome.loops)
            self.out(f"[task] {t}: complete（ループ {outcome.loops}）")

        return self._commit_stage(state, t, rec)

    def _run_child(self, state: dict[str, Any], t: str, rec: dict[str, Any], remaining: int) -> Outcome | RunResult:
        resume_child = rec["status"] in ("running", "interrupted")
        # 子の呼び出し回数は累積（再開時は前回分を含む）。このタスクの上限 = 既に使った分 + 全体の残り
        task_cap = rec.get("calls", 0) + remaining
        child_cfg = dataclasses.replace(self.cfg, max_total_calls=min(self.cfg.max_total_calls, task_cap))
        ctrl = Controller(child_cfg, self.repo, allow_real=self.allow_real, out=self.out)
        rec["status"] = "running"
        self._save(state)
        self.store.log("autopilot_task_start", task=t, resume=resume_child)
        self.out(f"[task] {t} を開始{'（再開）' if resume_child else ''}")
        try:
            child = self._child_store_state(t) if resume_child else None
            if child is not None and child.get("status") in ("complete", "stopped"):
                outcome = _outcome_from_state(child)  # 子が既に終わっていたら再実行しない
            elif resume_child:
                outcome = ctrl.run(t, resume=True)
            else:
                outcome = ctrl.run(t)
        except KeyboardInterrupt:
            rec["status"] = "interrupted"
            self._save(state)
            raise
        except ConfigError as exc:
            rec["status"] = "stopped"
            self._save(state)
            return self._stop(state, t, "child_config_error", str(exc))
        rec["calls"] = outcome.calls
        rec["reason"] = outcome.reason
        self._save(state)
        return outcome

    # ------------------------------------------------ commit / push

    def _commit_stage(self, state: dict[str, Any], t: str, rec: dict[str, Any]) -> RunResult | None:
        if not self.commit_enabled:
            return self._stop(state, t, "commit_disabled",
                              "完了したが commit が無効（queue.allow_commit と --commit が必要）。作業ツリーに変更が残っている")
        branch = gitwrite.current_branch(self.repo)
        if gitwrite.is_protected(branch):
            return self._stop(state, t, "protected_branch", f"保護されたブランチには commit しない: {branch}")
        if branch != state["branch"]:
            return self._stop(state, t, "branch_changed", f"ブランチが変わっている: {state['branch']} → {branch}")

        entries = [(c, p) for c, p in gitutil.status_entries(self.repo)
                   if not p.replace("\\", "/").startswith(self.state_prefix)]
        if not entries:
            sha = gitwrite.find_trailer_commit(self.repo, t)
            if sha is None:
                return self._stop(state, t, "nothing_to_commit", "変更がないのに commit 記録もない")
            rec.update(status="committed", commit=sha)  # 既に commit 済み（再開時）
            self._save(state)
            self.out(f"[commit] {t}: 既に commit 済み {sha[:10]}")
            return self._push_stage(state, t, branch)

        report = classify_changes(entries, self.cfg.protected_paths, self.cfg.allow_delete,
                                  ignore_prefixes=(self.state_prefix,))
        if report.forbidden:
            return self._stop(state, t, "forbidden_change", "; ".join(report.forbidden[:10]))
        try:
            for p in report.changed:
                safe_repo_path(self.repo, p)
        except SafetyError as exc:
            return self._stop(state, t, "unsafe_path", str(exc))
        res_rel = result_rel(self.cfg.instructions_dir, rec["number"])
        if res_rel not in report.changed:
            return self._stop(state, t, "result_not_changed", f"結果報告 {res_rel} が変更に含まれていない")

        try:
            gitwrite.stage(self.repo, sorted(report.changed))
            staged = gitwrite.staged_paths(self.repo)
            if staged != sorted(report.changed):
                return self._stop(state, t, "staging_mismatch", f"stage 結果が想定と違う: {staged[:10]}")
            message = (
                f"devloop: {t} を完了\n\n"
                f"{gitwrite.TRAILER_KEY} {t}\n"
                f"Devloop-Result: {res_rel}\n"
                f"Devloop-Calls: {rec.get('calls', 0)}\n"
            )
            sha = gitwrite.commit(self.repo, message)
        except gitwrite.GitWriteError as exc:
            return self._stop(state, t, "commit_failed", mask_secrets(str(exc)))
        rec.update(status="committed", commit=sha, files=sorted(report.changed))
        self._save(state)
        self.store.log("autopilot_commit", task=t, commit=sha, files=len(report.changed))
        self.out(f"[commit] {t}: {sha[:10]}（{len(report.changed)}件）")
        return self._push_stage(state, t, branch)

    def _push_stage(self, state: dict[str, Any], t: str, branch: str) -> RunResult | None:
        if not self.push_enabled:
            return None
        try:
            gitwrite.push(self.repo, "origin", branch)
        except gitwrite.GitWriteError as exc:
            return self._stop(state, t, "push_failed", mask_secrets(str(exc)))
        self.store.log("autopilot_push", task=t, branch=branch)
        self.out(f"[push] origin {branch}")
        return None


# ---------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m tools.devloop.autopilot",
                                description="監督ランナー: 登録された作業キューを順に実行（既定は dry-run）")
    p.add_argument("--repo", required=True, help="対象のGit作業ツリーのルート（使い捨てクローン推奨）")
    p.add_argument("--queue", required=True, help="作業キュー（YAML/JSON）")
    p.add_argument("--config", help="devloop の設定ファイル。省略時は <repo>/devloop.yaml")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="計画を表示するだけ（既定）")
    mode.add_argument("--execute", action="store_true", help="実行する（設定の dry_run: false も必要）")
    p.add_argument("--allow-real", action="store_true", help="実AIのCLI起動を許可（設定の allow_real_cli: true も必要）")
    p.add_argument("--commit", action="store_true", help="成功したタスクを commit する（queue の allow_commit も必要）")
    p.add_argument("--push", action="store_true", help="commit 後に作業ブランチを push する（allow_push も必要）")
    p.add_argument("--resume", action="store_true", help="中断・停止した実行を再開する")
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    config_path = args.config or os.path.join(args.repo, "devloop.yaml")
    try:
        cfg = load_config(config_path)
        queue = load_queue(args.queue, cfg)
        runner = Runner(cfg, queue, args.repo, allow_real=args.allow_real, commit=args.commit, push=args.push)
        if not args.execute:
            result = runner.plan()
        else:
            result = runner.run(resume=args.resume)
    except (OSError, ConfigError, SafetyError, gitutil.GitError, gitwrite.GitWriteError) as exc:
        print(f"設定エラー: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
