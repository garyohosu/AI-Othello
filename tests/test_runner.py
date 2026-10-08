import os
import sys
import time

import pytest

import ai_runner
import game
from ai_runner import AIPlayer, ModelConfig

MOCK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_cli.py")
INITIAL_TEXT = game.format_board(game.initial_board())


def mock_cfg(actions: str, **extra) -> ModelConfig:
    data = {
        "id": "mock",
        "provider": "mock",
        "model": "m",
        "command": ["{python}", MOCK, "--actions", actions, "--seconds", "5"],
    }
    data.update(extra)
    return ModelConfig.from_dict(data)


def ask(actions: str, timeout: float = 20, **extra) -> ai_runner.Attempt:
    return AIPlayer(mock_cfg(actions, **extra), default_timeout_sec=timeout).ask(INITIAL_TEXT, game.BLACK)


# ---------------------------------------------------------------- プロンプト


def test_prompt_contains_required_parts_only():
    prompt = ai_runner.build_prompt(INITIAL_TEXT, game.BLACK)
    assert prompt.startswith(ai_runner.COMMON_INSTRUCTION)
    assert "あなたの色: 黒（●）" in prompt
    assert "●=黒、〇=白、□=空き" in prompt
    assert "列は左からA～H、行は上から1～8" in prompt
    assert prompt.endswith("盤面:\n" + INITIAL_TEXT)
    # 合法手を渡していない
    for move in ["C4", "D3", "E6", "F5"]:
        assert move not in prompt


def test_prompt_differs_only_in_color():
    black = ai_runner.build_prompt(INITIAL_TEXT, game.BLACK)
    white = ai_runner.build_prompt(INITIAL_TEXT, game.WHITE)
    assert black.replace("黒（●）", "X") == white.replace("白（〇）", "X")


# ---------------------------------------------------------------- 回答形式


@pytest.mark.parametrize("answer, kind", [
    ("D3", "move"), ("A1", "move"), ("H8", "move"), ("PASS", "pass"),
    ("d3", "format"), ("pass", "format"), ("Pass", "format"), ("", "format"),
    ("I9", "format"), ("A0", "format"), ("Z99", "format"), ("D3です", "format"),
    ("D3 E4", "format"), ("`D3`", "format"), ("D 3", "format"), ("D3\nD4", "format"),
])
def test_classify_answer(answer, kind):
    assert ai_runner.classify_answer(answer) == kind


def test_extract_text_strips_whitespace():
    cfg = mock_cfg("legal")
    assert ai_runner.extract_body("  \n D3 \r\n", cfg).body == "D3"


def test_extract_does_not_pick_coordinate_from_explanation():
    cfg = mock_cfg("legal")
    body = ai_runner.extract_body("私はD3に打ちます\n", cfg).body
    assert body == "私はD3に打ちます"
    assert ai_runner.classify_answer(body) == "format"


def test_extract_json_field_and_usage():
    cfg = mock_cfg("json", output="json", json_field="result",
                   usage_fields={"input_tokens": "usage.input_tokens", "cost_usd": "total_cost_usd",
                                 "actual_model": "missing.path"})
    ext = ai_runner.extract_body('{"result": " PASS\\n", "usage": {"input_tokens": 5}, "total_cost_usd": 0.1}', cfg)
    assert ext.body == "PASS"
    assert ext.meta == {"input_tokens": 5, "cost_usd": 0.1, "actual_model": None}


@pytest.mark.parametrize("stdout", ['{"result": "D3"', '{"other": "D3"}', '{"result": 3}', "D3"])
def test_extract_json_failure_is_parse_error(stdout):
    cfg = mock_cfg("json", output="json", json_field="result")
    ext = ai_runner.extract_body(stdout, cfg)
    assert ext.body is None and ext.error


# ---------------------------------------------------------------- 設定


def test_config_validation():
    with pytest.raises(ai_runner.ConfigError):
        ModelConfig.from_dict({"id": "a", "provider": "unknown", "model": "m", "command": ["x"]})
    with pytest.raises(ai_runner.ConfigError):
        ModelConfig.from_dict({"id": "a", "provider": "cli", "model": "m", "command": "claude -p"})
    with pytest.raises(ai_runner.ConfigError):
        ModelConfig.from_dict({"id": "a", "provider": "cli", "model": "m"})
    with pytest.raises(ai_runner.ConfigError):
        ModelConfig.from_dict({"id": "a", "provider": "cli", "model": "m", "command": ["x"], "output": "json"})
    with pytest.raises(ai_runner.ConfigError):
        ModelConfig.from_dict({"id": "a/b", "provider": "cli", "model": "m", "command": ["x"]})
    with pytest.raises(ai_runner.ConfigError):
        ai_runner.load_models({"models": [
            {"id": "a", "provider": "mock", "model": "m", "command": ["x"]},
            {"id": "a", "provider": "mock", "model": "m", "command": ["x"]},
        ]})


def test_sandbox_defaults():
    assert mock_cfg("legal").sandbox == "restricted"
    cfg = ModelConfig.from_dict({"id": "a", "provider": "cli", "model": "m", "command": ["x"]})
    assert cfg.sandbox == "unknown"


def test_example_config_loads():
    import yaml

    path = os.path.join(ai_runner.PROJECT_ROOT, "config", "models.example.yaml")
    with open(path, encoding="utf-8") as f:
        models = ai_runner.load_models(yaml.safe_load(f))
    assert [m.id for m in models] == ["mock-first", "mock-json"]


def test_mask_secrets(monkeypatch):
    monkeypatch.setenv("MY_API_KEY", "supersecretvalue123")
    text = "key=sk-abcdefghijklmnop xai-abcdefghijklmnop Bearer abc.def.ghijkl supersecretvalue123"
    masked = ai_runner.mask_secrets(text)
    for secret in ["sk-abcdefghijklmnop", "xai-abcdefghijklmnop", "abc.def.ghijkl", "supersecretvalue123"]:
        assert secret not in masked
    assert "Bearer ***MASKED***" in masked


# ---------------------------------------------------------------- モックCLI


def test_mock_cli_normal_move():
    attempt = ask("legal")
    assert attempt.error_type is None
    assert attempt.answer == "D3"
    assert attempt.exit_code == 0
    assert attempt.board_delivery == "inline"
    assert "盤面:" in attempt.prompt


@pytest.mark.parametrize("actions, answer", [
    ("format", "D3に打ちます"),
    ("lower", "d3"),
    ("empty", ""),
    ("illegal", "D4"),
    ("pass", "PASS"),
])
def test_mock_cli_answers_are_returned_as_is(actions, answer):
    attempt = ask(actions)
    assert attempt.error_type is None
    assert attempt.answer == answer


def test_empty_answer_is_format_foul_not_technical_error():
    attempt = ask("empty")
    assert attempt.error_type is None
    assert ai_runner.classify_answer(attempt.answer) == "format"


def test_mock_cli_json():
    attempt = ask("json", output="json", json_field="result",
                  usage_fields={"input_tokens": "usage.input_tokens", "output_tokens": "usage.output_tokens",
                                "cost_usd": "total_cost_usd", "actual_model": "model"})
    assert attempt.answer == "D3"
    assert attempt.meta == {"input_tokens": 120, "output_tokens": 2, "cost_usd": 0.0001,
                            "actual_model": "mock-model-1"}


def test_mock_cli_broken_json_is_parse_error():
    attempt = ask("badjson", output="json", json_field="result")
    assert attempt.error_type == ai_runner.PARSE
    assert attempt.answer is None
    assert attempt.raw_stdout.strip() == '{"result": "D3"'


def test_mock_cli_timeout():
    start = time.monotonic()
    attempt = ask("sleep", timeout=1)
    assert attempt.error_type == ai_runner.TIMEOUT
    assert attempt.answer is None
    assert time.monotonic() - start < 4.5


def test_mock_cli_nonzero_exit():
    attempt = ask("exit")
    assert attempt.error_type == ai_runner.NONZERO_EXIT
    assert attempt.exit_code == 1
    assert "something failed" in attempt.raw_stderr


def test_mock_cli_auth_error():
    attempt = ask("auth")
    assert attempt.error_type == ai_runner.AUTH


def test_launch_failure():
    cfg = ModelConfig.from_dict({"id": "x", "provider": "cli", "model": "m",
                                 "command": ["no-such-command-ai-othello"]})
    attempt = AIPlayer(cfg).ask(INITIAL_TEXT, game.BLACK)
    assert attempt.error_type == ai_runner.LAUNCH


def test_counter_switches_actions(tmp_path):
    counter = str(tmp_path / "count")
    cfg = mock_cfg("exit,legal")
    cfg.command += ["--counter", counter]
    player = AIPlayer(cfg)
    assert player.ask(INITIAL_TEXT, game.BLACK).error_type == ai_runner.NONZERO_EXIT
    assert player.ask(INITIAL_TEXT, game.BLACK).answer == "D3"
    assert player.ask(INITIAL_TEXT, game.BLACK).answer == "D3"


def test_cli_version():
    cfg = mock_cfg("legal", version_command=["{python}", "--version"])
    assert AIPlayer(cfg).cli_version().startswith("Python ")
    assert AIPlayer(mock_cfg("legal")).cli_version() is None


def test_resolve_command_placeholders():
    argv = ai_runner.resolve_command(["{python}", "{project}/x.py", "--model", "{model}"], "abc")
    assert os.path.samefile(argv[0], sys.executable)
    assert argv[1] == ai_runner.PROJECT_ROOT + "/x.py"
    assert argv[3] == "abc"
