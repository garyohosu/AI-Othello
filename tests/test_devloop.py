"""tools/devloop（汎用AI自動開発ループ）のテスト。実AIは一度も呼ばない。"""

import json
import os
import subprocess
import sys

import pytest

from tools.devloop import adapters, controller, gitutil, safety, schema
from tools.devloop.controller import Config, ConfigError, Controller

MOCKS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "devloop_mocks")
IMPL = os.path.join(MOCKS, "mock_implementer.py")
REVIEWER = os.path.join(MOCKS, "mock_reviewer.py")


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                   check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / "instructions").mkdir(parents=True)
    (r / "instructions" / "Instruction00001.md").write_text("# Instruction00001\n\nsrc.txt を作る\n", encoding="utf-8")
    (r / "check.py").write_text(
        "import os, sys\n"
        "sys.exit(int(open('status.txt').read()) if os.path.exists('status.txt') else 0)\n",
        encoding="utf-8",
    )
    (r / "keep.txt").write_text("keep\n", encoding="utf-8")
    (r / "requirements.txt").write_text("PyYAML\n", encoding="utf-8")
    (r / ".gitignore").write_text(".devloop/\n", encoding="utf-8")
    git(r, "init", "-q")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "init")
    return r


def review(decision, summary="ok", issues=(), next_instruction=None):
    return {"review": {"decision": decision, "summary": summary, "issues": list(issues),
                       "next_instruction": next_instruction}}


RETRY = review("retry", "修正が必要", ["src.txt がない"], "src.txt を作成すること")
COMPLETE = review("complete", "完了")


def make_config(tmp_path, impl_steps, review_steps, **extra):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    (work / "impl.json").write_text(json.dumps(impl_steps, ensure_ascii=False), encoding="utf-8")
    (work / "review.json").write_text(json.dumps(review_steps, ensure_ascii=False), encoding="utf-8")
    data = {
        "dry_run": False,
        "implementer": {
            "provider": "mock",
            "command": ["{python}", IMPL, "--scenario", str(work / "impl.json"), "--counter",
                        str(work / "impl.count"), "--result", "{result}", "--instruction", "{instruction}"],
            "timeout_sec": 30,
        },
        "reviewer": {
            "provider": "mock",
            "command": ["{python}", REVIEWER, "--scenario", str(work / "review.json"), "--counter",
                        str(work / "review.count"), "--prompt-out", str(work / "last_prompt.txt")],
            "timeout_sec": 30,
        },
        "test_commands": [["{python}", "check.py"]],
        "test_timeout_sec": 60,
        "max_loops": 3,
        "max_total_calls": 10,
    }
    data.update(extra)
    return Config.from_dict(data)


def run(tmp_path, repo, impl_steps, review_steps, instr="instructions/Instruction00001.md", **extra):
    cfg = make_config(tmp_path, impl_steps, review_steps, **extra)
    return Controller(cfg, str(repo), out=lambda s: None).run(instr)


def count(tmp_path, name):
    p = tmp_path / "work" / f"{name}.count"
    return int(p.read_text()) if p.exists() else 0


# ---------------------------------------------------------------- 閉ループ


def test_retry_then_complete_in_two_loops(tmp_path, repo):
    out = run(tmp_path, repo, [{"touch": ["src.txt"]}], [RETRY, COMPLETE])
    assert out.status == "complete" and out.reason == "complete", out
    assert out.loops == 2 and out.exit_code == 0
    nxt = (repo / "instructions" / "Instruction00002.md").read_text(encoding="utf-8")
    assert "src.txt を作成すること" in nxt and "instructions/Result00002.md" in nxt
    assert "信頼できない入力" in nxt
    assert (repo / "instructions" / "Result00001.md").exists()
    assert (repo / "instructions" / "Result00002.md").exists()
    assert count(tmp_path, "impl") == 2 and count(tmp_path, "review") == 2
    state = json.loads((repo / ".devloop" / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "complete" and state["calls"] == 4
    assert [h["review"]["decision"] for h in state["history"]] == ["retry", "complete"]
    # テストはコントローラが実際に実行し、終了コードを記録している
    assert state["history"][0]["checks"]["tests"][0]["exit_code"] == 0
    # コントローラはコミットしない
    assert gitutil.head(str(repo)) == state["start_head"]
    # レビュー担当には機械的チェックの結果と差分が渡っている
    prompt = (tmp_path / "work" / "last_prompt.txt").read_text(encoding="utf-8")
    assert "全テスト成功: True" in prompt and "src.txt" in prompt


def test_blocked_stops(tmp_path, repo):
    out = run(tmp_path, repo, [{}], [review("blocked", "人間の判断が必要")])
    assert out.status == "stopped" and out.reason == "blocked" and out.exit_code == 3, out
    assert not (repo / "instructions" / "Instruction00002.md").exists()


@pytest.mark.parametrize("step", [
    {"raw": "complete"},
    {"raw": '{"decision": "complete"'},
    {"raw": 'はい。{"decision": "complete", "summary": "", "issues": [], "next_instruction": null}'},
    {"review": {"decision": "complete", "summary": "x", "issues": []}},
    {"review": {"decision": "done", "summary": "x", "issues": [], "next_instruction": None}},
    {"review": {"decision": "retry", "summary": "x", "issues": [], "next_instruction": None}},
    {"raw": ""},
], ids=["text", "broken", "prefixed", "missing-key", "bad-decision", "retry-without-next", "empty"])
def test_invalid_review_stops(tmp_path, repo, step):
    out = run(tmp_path, repo, [{}], [step])
    assert out.reason == "invalid_review", out
    assert not (repo / "instructions" / "Instruction00002.md").exists()


def test_missing_result_stops_before_review(tmp_path, repo):
    out = run(tmp_path, repo, [{"write_result": False}], [COMPLETE])
    assert out.reason == "result_missing", out
    assert count(tmp_path, "review") == 0


def test_result_without_heading_or_required_section_stops(tmp_path, repo):
    out = run(tmp_path, repo, [{"result_text": "見出しなし"}], [COMPLETE])
    assert out.reason == "result_invalid", out


def test_required_sections(tmp_path, repo):
    out = run(tmp_path, repo, [{}], [COMPLETE], result_required_sections=["変更ファイル"])
    assert out.reason == "result_invalid" and "変更ファイル" in out.detail, out


def test_failed_tests_cannot_complete(tmp_path, repo):
    out = run(tmp_path, repo, [{"test_status": "fail"}], [COMPLETE])
    assert out.reason == "inconsistent_review", out
    state = json.loads((repo / ".devloop" / "state.json").read_text(encoding="utf-8"))
    assert state["history"][0]["checks"]["tests"][0]["exit_code"] == 1
    assert state["history"][0]["checks"]["tests_passed"] is False


def test_failed_tests_then_fixed(tmp_path, repo):
    out = run(tmp_path, repo, [{"test_status": "fail"}, {"test_status": "pass"}], [RETRY, COMPLETE])
    assert out.status == "complete" and out.loops == 2, out


def test_implementer_timeout(tmp_path, repo):
    cfg_extra = {}
    cfg = make_config(tmp_path, [{"sleep": 10}], [COMPLETE], **cfg_extra)
    cfg.implementer.timeout_sec = 1
    out = Controller(cfg, str(repo), out=lambda s: None).run("instructions/Instruction00001.md")
    assert out.reason == "technical_error" and "タイムアウト" in out.detail, out
    assert count(tmp_path, "review") == 0


def test_reviewer_timeout(tmp_path, repo):
    cfg = make_config(tmp_path, [{}], [{"sleep": 10}])
    cfg.reviewer.timeout_sec = 1
    out = Controller(cfg, str(repo), out=lambda s: None).run("instructions/Instruction00001.md")
    assert out.reason == "technical_error" and "レビュー担当" in out.detail, out


def test_nonzero_exit(tmp_path, repo):
    out = run(tmp_path, repo, [{"exit": 2}], [COMPLETE])
    assert out.reason == "technical_error" and "非ゼロ終了: 2" in out.detail, out


def test_reviewer_nonzero_exit(tmp_path, repo):
    out = run(tmp_path, repo, [{}], [{"exit": 1}])
    assert out.reason == "technical_error" and "レビュー担当" in out.detail, out


def test_max_three_loops(tmp_path, repo):
    retries = [review("retry", f"r{i}", [f"指摘{i}"], f"作業{i}") for i in range(5)]
    out = run(tmp_path, repo, [{}], retries)
    assert out.reason == "max_loops" and out.loops == 3, out
    assert (repo / "instructions" / "Instruction00003.md").exists()
    assert not (repo / "instructions" / "Instruction00004.md").exists()
    assert count(tmp_path, "impl") == 3 and count(tmp_path, "review") == 3


def test_max_loops_configurable(tmp_path, repo):
    retries = [review("retry", f"r{i}", [f"指摘{i}"], f"作業{i}") for i in range(5)]
    out = run(tmp_path, repo, [{}], retries, max_loops=1)
    assert out.reason == "max_loops" and out.loops == 1, out
    assert not (repo / "instructions" / "Instruction00002.md").exists()


def test_max_loops_above_three_is_rejected(tmp_path):
    with pytest.raises(ConfigError):
        make_config(tmp_path, [{}], [COMPLETE], max_loops=4)


def test_repeated_same_failure_stops(tmp_path, repo):
    out = run(tmp_path, repo, [{}], [RETRY, RETRY, COMPLETE])
    assert out.reason == "repeated_failure" and out.loops == 2, out


def test_total_call_limit(tmp_path, repo):
    retries = [review("retry", f"r{i}", [f"指摘{i}"], f"作業{i}") for i in range(5)]
    out = run(tmp_path, repo, [{}], retries, max_total_calls=3)
    assert out.reason == "max_calls", out
    assert count(tmp_path, "impl") + count(tmp_path, "review") == 3


# ---------------------------------------------------------------- 番号衝突・上書き防止


def test_next_instruction_number_conflict_does_not_overwrite(tmp_path, repo):
    existing = "# 既存の指示書\n"
    (repo / "instructions" / "Instruction00002.md").write_text(existing, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "add 2")
    out = run(tmp_path, repo, [{}], [RETRY])
    assert out.reason == "number_conflict", out
    assert (repo / "instructions" / "Instruction00002.md").read_text(encoding="utf-8") == existing


def test_next_result_conflict(tmp_path, repo):
    (repo / "instructions" / "Result00002.md").write_text("# 既存\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "add r2")
    out = run(tmp_path, repo, [{}], [RETRY])
    assert out.reason == "number_conflict", out
    assert not (repo / "instructions" / "Instruction00002.md").exists()


def test_existing_result_is_not_overwritten(tmp_path, repo):
    (repo / "instructions" / "Result00001.md").write_text("# 既存の結果\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "add r1")
    out = run(tmp_path, repo, [{}], [COMPLETE])
    assert out.reason == "number_conflict", out
    assert count(tmp_path, "impl") == 0
    assert (repo / "instructions" / "Result00001.md").read_text(encoding="utf-8") == "# 既存の結果\n"


def test_dirty_worktree_is_not_touched(tmp_path, repo):
    (repo / "keep.txt").write_text("ユーザーの未コミット変更\n", encoding="utf-8")
    out = run(tmp_path, repo, [{}], [COMPLETE])
    assert out.reason == "dirty_worktree", out
    assert count(tmp_path, "impl") == 0
    assert (repo / "keep.txt").read_text(encoding="utf-8") == "ユーザーの未コミット変更\n"


# ---------------------------------------------------------------- 禁止操作の検出


def test_implementer_commit_is_detected(tmp_path, repo):
    out = run(tmp_path, repo, [{"commit": True}], [COMPLETE])
    assert out.reason == "forbidden_change" and "コミット" in out.detail, out
    assert count(tmp_path, "review") == 0


def test_file_deletion_is_detected(tmp_path, repo):
    out = run(tmp_path, repo, [{"delete": ["keep.txt"]}], [COMPLETE])
    assert out.reason == "forbidden_change" and "keep.txt" in out.detail, out


def test_dependency_change_is_detected(tmp_path, repo):
    out = run(tmp_path, repo, [{"touch": ["requirements.txt"]}], [COMPLETE])
    assert out.reason == "forbidden_change" and "requirements.txt" in out.detail, out


def test_reviewer_modification_is_detected(tmp_path, repo):
    out = run(tmp_path, repo, [{}], [{"touch": ["keep.txt"], **COMPLETE}])
    assert out.reason == "reviewer_modified_repo", out


def test_reviewer_editing_untracked_result_is_detected(tmp_path, repo):
    out = run(tmp_path, repo, [{}], [{"touch": ["instructions/Result00001.md"], **COMPLETE}])
    assert out.reason == "reviewer_modified_repo", out


# ---------------------------------------------------------------- dry-run・実AIの許可


@pytest.fixture
def no_process(monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("プロセスを起動してはいけない")

    monkeypatch.setattr(adapters, "run_process", forbidden)
    monkeypatch.setattr(controller, "run_process", forbidden)
    monkeypatch.setattr(controller, "run_role", forbidden)


def test_dry_run_starts_no_process_and_writes_nothing(tmp_path, repo, no_process):
    cfg = make_config(tmp_path, [{}], [COMPLETE])
    lines = []
    out = Controller(cfg, str(repo), out=lines.append).plan("instructions/Instruction00001.md")
    assert out.status == "dry_run" and out.exit_code == 0, out
    assert any("dry-run" in line for line in lines)
    assert not (repo / ".devloop").exists()
    assert not (tmp_path / "work" / "impl.count").exists()


def test_dry_run_is_default_in_cli(tmp_path, repo, no_process, capsys):
    data = {
        "implementer": {"provider": "mock", "command": ["{python}", IMPL]},
        "reviewer": {"provider": "mock", "command": ["{python}", REVIEWER]},
        "test_commands": [["{python}", "check.py"]],
    }
    json_path = tmp_path / "devloop.json"
    json_path.write_text(json.dumps(data), encoding="utf-8")
    code = controller.main(["--repo", str(repo), "--instruction", "instructions/Instruction00001.md",
                            "--config", str(json_path)])
    assert code == 0
    assert "dry-run" in capsys.readouterr().out
    # 設定が dry_run: true（既定）のままなら --execute でも実行しない
    code = controller.main(["--repo", str(repo), "--instruction", "instructions/Instruction00001.md",
                            "--config", str(json_path), "--execute"])
    assert code == 2
    assert not (repo / ".devloop").exists()


def test_real_ai_requires_two_approvals(tmp_path, repo, no_process):
    data = {
        "dry_run": False,
        "implementer": {"provider": "claude", "command": ["claude", "-p", "{prompt}"]},
        "reviewer": {"provider": "codex", "command": ["codex", "exec", "-s", "read-only", "-"]},
        "test_commands": [["{python}", "check.py"]],
    }
    cfg = Config.from_dict(data)
    out = Controller(cfg, str(repo), allow_real=True, out=lambda s: None).run("instructions/Instruction00001.md")
    assert out.reason == "approval_required"  # 設定側の allow_real_cli がない, out
    cfg = Config.from_dict({**data, "allow_real_cli": True})
    out = Controller(cfg, str(repo), allow_real=False, out=lambda s: None).run("instructions/Instruction00001.md")
    assert out.reason == "approval_required"  # --allow-real がない, out
    assert not (repo / ".devloop").exists()


def test_real_cli_cannot_be_registered_as_mock():
    for exe in ["claude", "codex", "C:/x/codex.cmd", "gemini"]:
        with pytest.raises(ConfigError):
            Config.from_dict({
                "implementer": {"provider": "mock", "command": [exe]},
                "reviewer": {"provider": "mock", "command": ["{python}", REVIEWER]},
                "test_commands": [["{python}", "check.py"]],
            })


def test_example_config_is_safe():
    path = os.path.join(os.path.dirname(MOCKS), "..", "tools", "devloop", "config.example.yaml")
    cfg = controller.load_config(path)
    assert cfg.dry_run is True and cfg.allow_real_cli is False
    assert cfg.max_loops <= 3
    assert cfg.implementer.provider == "claude" and cfg.reviewer.provider == "codex"


# ---------------------------------------------------------------- テストコマンドの境界


@pytest.mark.parametrize("argv", [["git", "push"], ["cmd", "/c", "echo"], ["powershell", "-c", "x"], ["rm", "-rf", "."]])
def test_disallowed_test_commands(argv):
    with pytest.raises(safety.SafetyError):
        safety.check_test_command(argv, safety.DEFAULT_ALLOWED_TEST_EXECUTABLES)


def test_allowed_test_command_resolves():
    argv = safety.check_test_command(["{python}", "-c", "pass"], safety.DEFAULT_ALLOWED_TEST_EXECUTABLES)
    assert os.path.samefile(argv[0], sys.executable)


def test_disallowed_test_command_in_config_is_config_error(tmp_path, repo):
    cfg = make_config(tmp_path, [{}], [COMPLETE], test_commands=[["git", "status"]])
    with pytest.raises(ConfigError):
        Controller(cfg, str(repo), out=lambda s: None).run("instructions/Instruction00001.md")


# ---------------------------------------------------------------- パス


@pytest.mark.parametrize("rel", ["../x.md", "instructions/../../x.md", "C:/x.md", "/x.md", "\\x.md", "", "a//b"])
def test_unsafe_paths_are_rejected(tmp_path, rel):
    with pytest.raises(safety.SafetyError):
        safety.safe_repo_path(str(tmp_path), rel)


def test_symlink_path_is_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    repo_dir = tmp_path / "r"
    repo_dir.mkdir()
    try:
        os.symlink(outside, repo_dir / "instructions", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("この環境ではシンボリックリンクを作れない")
    with pytest.raises(safety.SafetyError):
        safety.safe_repo_path(str(repo_dir), "instructions/Instruction00002.md")


def test_instruction_name_rules():
    assert safety.instruction_number("instructions/Instruction00003.md", "instructions") == 3
    for bad in ["instructions/Instruction3.md", "other/Instruction00003.md", "instructions/x/Instruction00003.md",
                "instructions/Result00003.md"]:
        with pytest.raises(safety.SafetyError):
            safety.instruction_number(bad, "instructions")


def test_instruction_outside_instructions_dir_is_config_error(tmp_path, repo):
    (repo / "Instruction00001.md").write_text("# x\n", encoding="utf-8")
    cfg = make_config(tmp_path, [{}], [COMPLETE])
    with pytest.raises(ConfigError):
        Controller(cfg, str(repo), out=lambda s: None).run("Instruction00001.md")


# ---------------------------------------------------------------- 再開・ログ


def test_interrupt_and_resume(tmp_path, repo, monkeypatch):
    cfg = make_config(tmp_path, [{"touch": ["src.txt"]}], [COMPLETE])
    real_run_role = controller.run_role
    calls = {"n": 0}

    def interrupting(role, *a, **k):
        if role.name == "reviewer" and calls["n"] == 0:
            calls["n"] += 1
            raise KeyboardInterrupt
        return real_run_role(role, *a, **k)

    monkeypatch.setattr(controller, "run_role", interrupting)
    out = Controller(cfg, str(repo), out=lambda s: None).run("instructions/Instruction00001.md")
    assert out.status == "interrupted" and out.exit_code == 130, out
    with pytest.raises(ConfigError):
        Controller(cfg, str(repo), out=lambda s: None).run("instructions/Instruction00001.md")
    out = Controller(cfg, str(repo), out=lambda s: None).run(None, resume=True)
    assert out.status == "complete", out
    assert count(tmp_path, "impl") == 1  # 実装は再実行しない


def test_log_masks_secrets(tmp_path, repo):
    out = run(tmp_path, repo, [{"print": "token sk-abcdefghijklmnopqrstuvwx"}], [COMPLETE])
    assert out.status == "complete", out
    log = (repo / ".devloop" / "log.jsonl").read_text(encoding="utf-8")
    state = (repo / ".devloop" / "state.json").read_text(encoding="utf-8")
    assert "sk-abcdefghijklmnopqrstuvwx" not in log and "sk-abcdefghijklmnopqrstuvwx" not in state
    assert "***MASKED***" in log


# ---------------------------------------------------------------- スキーマ


def test_review_schema():
    ok = schema.parse_review('{"decision": "retry", "summary": "s", "issues": ["a"], "next_instruction": "do"}')
    assert ok.decision == "retry" and ok.issues == ("a",)
    assert schema.parse_review(' {"decision": "complete", "summary": "", "issues": [], "next_instruction": null}\n')
    for bad in [
        '{"decision": "complete", "summary": "", "issues": [], "next_instruction": null, "extra": 1}',
        '{"decision": "complete", "summary": 1, "issues": [], "next_instruction": null}',
        '{"decision": "complete", "summary": "", "issues": [1], "next_instruction": null}',
        '["complete"]',
        "```json\n{}\n```",
    ]:
        with pytest.raises(schema.ReviewSchemaError):
            schema.parse_review(bad)
    assert schema.REVIEW_JSON_SCHEMA["additionalProperties"] is False


# ---------------------------------------------------------------- プロンプトの渡し方（標準入力）

EXAMPLE_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "devloop", "config.example.yaml")


def _stdin_reviewer_role(tmp_path, prompt_out):
    work = tmp_path / "stdin_work"
    work.mkdir(exist_ok=True)
    (work / "scenario.json").write_text(json.dumps([COMPLETE], ensure_ascii=False), encoding="utf-8")
    return adapters.RoleConfig(
        name="reviewer", provider="mock", timeout_sec=30,
        command=["{python}", REVIEWER, "--scenario", str(work / "scenario.json"),
                 "--counter", str(work / "counter.txt"), "--prompt-out", str(prompt_out)],
    )


def test_prompt_reaches_child_stdin_byte_exact(tmp_path):
    # 日本語・改行・記号・絵文字・タブを含み、64KiB を超える長文。cp932 の既定では読めない内容。
    prompt = "オセロの指示書です。\n改行・記号 !@#$%^&*()「」『』、。\t絵文字 🎲♟\n" * 2000
    assert len(prompt.encode("utf-8")) > 64 * 1024
    out = tmp_path / "got.bin"
    res = adapters.run_role(_stdin_reviewer_role(tmp_path, out), prompt, {}, str(tmp_path))
    assert res.ok, res.describe_error()
    assert out.read_bytes() == prompt.encode("utf-8")


def test_long_prompt_is_not_passed_in_argv_without_placeholder():
    prompt = "長文" * 100_000  # 約600KB。引数で渡すと Windows の上限を超える
    argv, prompt_as_arg = adapters.resolve_argv(["{python}", "-c", "pass"], {"prompt": prompt})
    assert prompt_as_arg is False
    assert all(prompt not in a for a in argv)
    assert max(len(a) for a in argv) < 1000


def test_prompt_placeholder_still_passes_as_argument():
    argv, prompt_as_arg = adapters.resolve_argv(["{python}", "-c", "x", "{prompt}"], {"prompt": "こんにちは"})
    assert prompt_as_arg is True
    assert argv[-1] == "こんにちは"


def test_prompt_argument_is_rejected_for_cmd_wrapper(tmp_path):
    shim = tmp_path / "fake-cli.cmd"
    shim.write_text("@echo off\r\n", encoding="utf-8")
    with pytest.raises(adapters.AdapterError):
        adapters.resolve_argv([str(shim), "{prompt}"], {"prompt": "x"})


def test_child_that_ignores_stdin_does_not_hang_or_crash(tmp_path):
    # 長い入力を受け取らずに終了する子プロセスでも、例外にならず結果として返ること
    res = adapters.run_role(
        adapters.RoleConfig(name="reviewer", provider="mock", timeout_sec=30,
                            command=["{python}", "-c", "import sys; sys.exit(0)"]),
        "長文" * 300_000, {}, str(tmp_path),
    )
    assert res.launch_error is None and not res.timed_out


def test_example_claude_command_sends_prompt_via_stdin():
    cfg = controller.load_config(EXAMPLE_CONFIG)
    cmd = cfg.implementer.command
    assert cmd[:2] == ["claude", "-p"]
    assert not any("{prompt}" in part for part in cmd)
