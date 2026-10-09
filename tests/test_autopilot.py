"""監督ランナー（tools/devloop/autopilot.py）のテスト。実AIは呼ばない。Git は一時リポジトリ（とローカルの bare リモート）だけに対して行う。"""

import json
import os
import subprocess

import pytest

from tools.devloop import autopilot, gitutil, gitwrite
from tools.devloop.autopilot import Queue, Runner
from tools.devloop.controller import Config, ConfigError

MOCKS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "devloop_mocks")
IMPL = os.path.join(MOCKS, "mock_implementer.py")
REVIEWER = os.path.join(MOCKS, "mock_reviewer.py")
TASK1 = "instructions/Instruction00001.md"
TASK2 = "instructions/Instruction00004.md"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                          check=True, capture_output=True, text=True, encoding="utf-8").stdout


def review(decision, summary="ok", issues=(), next_instruction=None):
    return {"review": {"decision": decision, "summary": summary, "issues": list(issues),
                       "next_instruction": next_instruction}}


COMPLETE = review("complete", "完了")
RETRY = review("retry", "修正が必要", ["f1.txt がない"], "f1.txt を作成すること")
BLOCKED = review("blocked", "人間の判断が必要")


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / "instructions").mkdir(parents=True)
    for n in (1, 4):
        (r / "instructions" / f"Instruction{n:05d}.md").write_text(f"# Instruction{n:05d}\n\n作業 {n}\n", encoding="utf-8")
    (r / "check.py").write_text(
        "import os, sys\n"
        "sys.exit(int(open('status.txt').read()) if os.path.exists('status.txt') else 0)\n", encoding="utf-8")
    (r / "requirements.txt").write_text("PyYAML\n", encoding="utf-8")
    (r / ".gitignore").write_text(".devloop/\n", encoding="utf-8")
    git(r, "init", "-q", "-b", "main")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "init")
    git(r, "checkout", "-qb", "work/auto")
    return r


def make_cfg(tmp_path, impl_steps, review_steps, **extra):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    (work / "impl.json").write_text(json.dumps(impl_steps, ensure_ascii=False), encoding="utf-8")
    (work / "review.json").write_text(json.dumps(review_steps, ensure_ascii=False), encoding="utf-8")
    data = {
        "dry_run": False,
        "implementer": {"provider": "mock", "timeout_sec": 30, "command": [
            "{python}", IMPL, "--scenario", str(work / "impl.json"), "--counter", str(work / "impl.count"),
            "--result", "{result}", "--instruction", "{instruction}"]},
        "reviewer": {"provider": "mock", "timeout_sec": 30, "command": [
            "{python}", REVIEWER, "--scenario", str(work / "review.json"), "--counter", str(work / "review.count")]},
        "test_commands": [["{python}", "check.py"]],
        "test_timeout_sec": 60,
        "max_loops": 3,
        "max_total_calls": 10,
    }
    data.update(extra)
    return Config.from_dict(data)


def make_queue(cfg, tasks=(TASK1, TASK2), **extra):
    return Queue.from_dict({"tasks": list(tasks), "allow_commit": True, **extra}, cfg)


def count(tmp_path, name):
    p = tmp_path / "work" / f"{name}.count"
    return int(p.read_text()) if p.exists() else 0


def trailer_commits(repo):
    out = git(repo, "log", "--format=%H%x1f%B%x1e")
    result = []
    for rec in out.split("\x1e"):
        if "\x1f" in rec:
            sha, body = rec.split("\x1f", 1)
            if gitwrite.TRAILER_KEY in body:
                result.append((sha.strip(), body))
    return result


def state_of(repo):
    with open(os.path.join(repo, ".devloop", "autopilot.json"), encoding="utf-8") as f:
        return json.load(f)


def quiet(_):
    pass


# ---------------------------------------------------------------- 正常系


def test_two_tasks_complete_and_each_is_committed(tmp_path, repo):
    cfg = make_cfg(tmp_path, [{"touch": ["f1.txt"]}, {"touch": ["f2.txt"]}], [COMPLETE, COMPLETE])
    res = Runner(cfg, make_queue(cfg), str(repo), commit=True, out=quiet).run()
    assert res.status == "complete", res
    assert count(tmp_path, "impl") == 2 and count(tmp_path, "review") == 2
    commits = trailer_commits(repo)
    assert len(commits) == 2
    assert f"{gitwrite.TRAILER_KEY} {TASK1}" in commits[1][1] and f"{gitwrite.TRAILER_KEY} {TASK2}" in commits[0][1]
    assert "f1.txt" in git(repo, "show", "--name-only", "--format=", commits[1][0])
    assert "instructions/Result00001.md" in git(repo, "show", "--name-only", "--format=", commits[1][0])
    assert git(repo, "status", "--porcelain") == ""
    st = state_of(repo)
    assert st["status"] == "complete" and st["total_calls"] == 4
    assert all(t["status"] == "committed" for t in st["tasks"].values())


def test_retry_instruction_is_committed_with_its_task(tmp_path, repo):
    cfg = make_cfg(tmp_path, [{"touch": ["f1.txt"]}, {"touch": ["f1b.txt"]}, {"touch": ["f2.txt"]}],
                   [RETRY, COMPLETE, COMPLETE])
    res = Runner(cfg, make_queue(cfg), str(repo), commit=True, out=quiet).run()
    assert res.status == "complete", res
    commits = trailer_commits(repo)
    first = git(repo, "show", "--name-only", "--format=", commits[1][0])
    assert "instructions/Instruction00002.md" in first and "instructions/Result00002.md" in first
    assert "instructions/Instruction00004.md" not in first  # 次のキュー項目と混ざらない
    assert count(tmp_path, "impl") == 3
    assert [t["status"] for t in state_of(repo)["tasks"].values()] == ["committed", "committed"]


def test_rerun_does_not_duplicate_work_or_commits(tmp_path, repo):
    cfg = make_cfg(tmp_path, [{"touch": ["f1.txt"]}, {"touch": ["f2.txt"]}], [COMPLETE, COMPLETE])
    Runner(cfg, make_queue(cfg), str(repo), commit=True, out=quiet).run()
    head = gitutil.head(str(repo))
    res = Runner(cfg, make_queue(cfg), str(repo), commit=True, out=quiet).run(resume=True)
    assert res.status == "complete"
    assert gitutil.head(str(repo)) == head
    assert count(tmp_path, "impl") == 2 and len(trailer_commits(repo)) == 2


def test_fresh_start_refused_when_state_exists(tmp_path, repo):
    cfg = make_cfg(tmp_path, [{"touch": ["f1.txt"]}, {"touch": ["f2.txt"]}], [COMPLETE, COMPLETE])
    Runner(cfg, make_queue(cfg), str(repo), commit=True, out=quiet).run()
    with pytest.raises(ConfigError, match="状態がある"):
        Runner(cfg, make_queue(cfg), str(repo), commit=True, out=quiet).run()


# ---------------------------------------------------------------- 停止系（後続タスクを開始しない）


def test_blocked_stops_before_next_task(tmp_path, repo):
    cfg = make_cfg(tmp_path, [{"touch": ["f1.txt"]}, {"touch": ["f2.txt"]}], [BLOCKED, COMPLETE])
    res = Runner(cfg, make_queue(cfg), str(repo), commit=True, out=quiet).run()
    assert res.status == "stopped" and res.reason == "blocked"
    assert count(tmp_path, "impl") == 1
    assert not (repo / "instructions" / "Result00004.md").exists()
    assert trailer_commits(repo) == []
    assert state_of(repo)["tasks"][TASK2]["status"] == "pending"


def test_complete_with_failing_tests_is_not_committed(tmp_path, repo):
    cfg = make_cfg(tmp_path, [{"touch": ["f1.txt"], "test_status": "fail"}, {"touch": ["f2.txt"]}],
                   [COMPLETE, COMPLETE])
    res = Runner(cfg, make_queue(cfg), str(repo), commit=True, out=quiet).run()
    assert res.status == "stopped" and res.reason == "inconsistent_review"
    assert trailer_commits(repo) == [] and count(tmp_path, "impl") == 1


def test_forbidden_change_stops_without_commit(tmp_path, repo):
    cfg = make_cfg(tmp_path, [{"touch": ["requirements.txt"]}, {"touch": ["f2.txt"]}], [COMPLETE, COMPLETE])
    res = Runner(cfg, make_queue(cfg), str(repo), commit=True, out=quiet).run()
    assert res.status == "stopped" and res.reason == "forbidden_change"
    assert trailer_commits(repo) == [] and count(tmp_path, "impl") == 1


def test_call_budget_stops_before_next_task(tmp_path, repo):
    cfg = make_cfg(tmp_path, [{"touch": ["f1.txt"]}, {"touch": ["f2.txt"]}], [COMPLETE, COMPLETE])
    queue = make_queue(cfg, max_total_calls=2)
    res = Runner(cfg, queue, str(repo), commit=True, out=quiet).run()
    assert res.status == "stopped" and res.reason == "max_total_calls"
    assert len(trailer_commits(repo)) == 1
    assert state_of(repo)["tasks"][TASK2]["status"] == "pending" and count(tmp_path, "impl") == 1


def test_dirty_worktree_refused_at_start(tmp_path, repo):
    (repo / "stray.txt").write_text("x", encoding="utf-8")
    cfg = make_cfg(tmp_path, [{"touch": ["f1.txt"]}], [COMPLETE])
    res = Runner(cfg, make_queue(cfg), str(repo), commit=True, out=quiet).run()
    assert res.status == "stopped" and res.reason == "dirty_worktree"
    assert not (repo / ".devloop" / "autopilot.json").exists() and count(tmp_path, "impl") == 0


# ---------------------------------------------------------------- commit / push の境界


def test_commit_disabled_stops_and_resume_commits_without_rerunning(tmp_path, repo):
    cfg = make_cfg(tmp_path, [{"touch": ["f1.txt"]}, {"touch": ["f2.txt"]}], [COMPLETE, COMPLETE])
    res = Runner(cfg, make_queue(cfg), str(repo), commit=False, out=quiet).run()
    assert res.status == "stopped" and res.reason == "commit_disabled"
    assert trailer_commits(repo) == [] and count(tmp_path, "impl") == 1
    assert state_of(repo)["tasks"][TASK1]["status"] == "complete"

    res = Runner(cfg, make_queue(cfg), str(repo), commit=True, out=quiet).run(resume=True)
    assert res.status == "complete", res
    assert count(tmp_path, "impl") == 2 and count(tmp_path, "review") == 2  # 完了済みのタスク1は再実行しない
    assert len(trailer_commits(repo)) == 2


def test_protected_branch_is_never_committed(tmp_path, repo):
    git(repo, "checkout", "-q", "main")
    cfg = make_cfg(tmp_path, [{"touch": ["f1.txt"]}], [COMPLETE])
    res = Runner(cfg, make_queue(cfg), str(repo), commit=True, out=quiet).run()
    assert res.status == "stopped" and res.reason == "protected_branch"
    assert trailer_commits(repo) == []


def test_push_to_work_branch_on_local_bare_remote(tmp_path, repo):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    git(repo, "remote", "add", "origin", str(remote))
    cfg = make_cfg(tmp_path, [{"touch": ["f1.txt"]}, {"touch": ["f2.txt"]}], [COMPLETE, COMPLETE])
    queue = make_queue(cfg, allow_push=True)
    res = Runner(cfg, queue, str(repo), commit=True, push=True, out=quiet).run()
    assert res.status == "complete", res
    remote_sha = subprocess.run(["git", "-C", str(remote), "rev-parse", "refs/heads/work/auto"],
                                capture_output=True, text=True, check=True).stdout.strip()
    assert remote_sha == gitutil.head(str(repo))


def test_push_requires_flag_and_queue_permission(tmp_path, repo):
    cfg = make_cfg(tmp_path, [{"touch": ["f1.txt"]}], [COMPLETE])
    with pytest.raises(ConfigError, match="allow_commit"):
        Queue.from_dict({"tasks": [TASK1], "allow_push": True}, cfg)
    # queue で許可されていても --push（引数）が無ければ push しない
    queue = make_queue(cfg, tasks=(TASK1,), allow_push=True)
    r = Runner(cfg, queue, str(repo), commit=True, push=False, out=quiet)
    assert r.push_enabled is False and r.commit_enabled is True


def test_gitwrite_refuses_protected_branch_and_unsafe_paths(tmp_path, repo):
    with pytest.raises(gitwrite.GitWriteError):
        gitwrite.push(str(repo), "origin", "main")
    with pytest.raises(gitwrite.GitWriteError):
        gitwrite.push(str(repo), "origin", "master")
    with pytest.raises(gitwrite.GitWriteError):
        gitwrite.stage(str(repo), ["../outside.txt"])
    with pytest.raises(gitwrite.GitWriteError):
        gitwrite.stage(str(repo), ["-A"])
    git(repo, "checkout", "-q", "main")
    with pytest.raises(gitwrite.GitWriteError):
        gitwrite.commit(str(repo), "x")


# ---------------------------------------------------------------- 入力検証・dry-run


def test_numbering_overlap_is_rejected(tmp_path, repo):
    cfg = make_cfg(tmp_path, [{"touch": ["f1.txt"]}], [COMPLETE])  # max_loops 3
    (repo / "instructions" / "Instruction00002.md").write_text("# x\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="区画が重なる"):
        Queue.from_dict({"tasks": ["instructions/Instruction00001.md", "instructions/Instruction00002.md"]}, cfg)


def test_queue_limits_and_unknown_keys_are_rejected(tmp_path, repo):
    cfg = make_cfg(tmp_path, [{"touch": ["f1.txt"]}], [COMPLETE])
    with pytest.raises(ConfigError):
        Queue.from_dict({"tasks": [TASK1], "auto_merge": True}, cfg)
    with pytest.raises(ConfigError):
        Queue.from_dict({"tasks": [TASK1], "max_tasks": 0}, cfg)
    with pytest.raises(ConfigError):
        Queue.from_dict({"tasks": [TASK1], "max_total_calls": 1}, cfg)
    with pytest.raises(ConfigError):
        Queue.from_dict({"tasks": [TASK1, TASK1]}, cfg)


def test_dry_run_has_no_side_effects(tmp_path, repo):
    before = gitutil.head(str(repo))
    cfg = make_cfg(tmp_path, [{"touch": ["f1.txt"]}], [COMPLETE], dry_run=True)
    out = []
    res = Runner(cfg, make_queue(cfg, tasks=(TASK1,)), str(repo), commit=True, out=out.append).plan()
    assert res.status == "dry_run"
    assert not (repo / ".devloop").exists() and gitutil.head(str(repo)) == before
    assert count(tmp_path, "impl") == 0 and count(tmp_path, "review") == 0
    assert any("commit: 有効" in line for line in out)
    with pytest.raises(ConfigError, match="dry_run"):
        Runner(cfg, make_queue(cfg, tasks=(TASK1,)), str(repo), commit=True, out=quiet).run()


def test_real_ai_without_approval_stops_before_any_task(tmp_path, repo):
    cfg = Config.from_dict({
        "dry_run": False,
        "implementer": {"provider": "claude", "command": ["claude", "-p"]},
        "reviewer": {"provider": "codex", "command": ["codex", "exec", "-"]},
        "test_commands": [["{python}", "check.py"]],
    })
    res = Runner(cfg, make_queue(cfg, tasks=(TASK1,)), str(repo), commit=True, out=quiet).run()
    assert res.status == "stopped" and res.reason == "approval_required"
    assert not (repo / ".devloop").exists()
