import json
import stat
import sys
import textwrap

import pytest

from helpers import ctx
from jarvis.brain.backends.base import LLMError, LLMRetryableError
from jarvis.brain.backends.claude_code import ClaudeCodeBackend, ToolBridge
from jarvis.core.config import LLMConfig

FAKE = """\
#!{python}
import json, os, sys, time
log = os.environ["FAKE_CLAUDE_LOG"]
mode = open(os.environ["FAKE_CLAUDE_MODE"]).read().strip()
with open(log, "a") as f:
    f.write(json.dumps({{"argv": sys.argv[1:], "stdin": sys.stdin.read(), "cwd": os.getcwd()}}) + "\\n")
if mode == "ok":
    print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "result": "지금은 저녁이에요.",
        "session_id": "sess-123", "usage": {{"input_tokens": 40, "cache_read_input_tokens": 900, "output_tokens": 15}}}}))
elif mode == "login":
    print("Invalid API key · Please run /login", file=sys.stderr)
    sys.exit(1)
elif mode == "is_error":
    print(json.dumps({{"type": "result", "is_error": True, "result": "Claude usage limit reached"}}))
elif mode == "dyld":
    print("dyld[123]: Symbol not found ... (built for macOS 13.0 which is newer than running OS)", file=sys.stderr)
    sys.exit(134)
elif mode == "slow":
    time.sleep(5)
"""


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    exe = tmp_path / "claude"
    exe.write_text(FAKE.format(python=sys.executable))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "calls.jsonl"
    mode = tmp_path / "mode"
    mode.write_text("ok")
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    monkeypatch.setenv("FAKE_CLAUDE_MODE", str(mode))

    def calls():
        return [json.loads(line) for line in log.read_text().splitlines()]

    return exe, mode, calls


def make(tmp_path, exe, **cfg):
    config = LLMConfig(claude_code_path=str(exe), **cfg)
    return ClaudeCodeBackend(config, ToolBridge("http://127.0.0.1:8765", "tok"), "재원", tmp_path / "work")


async def test_success_and_resume(tmp_path, fake_claude):
    exe, _, calls = fake_claude
    backend = make(tmp_path, exe)
    assert backend.availability() == "ok"

    result = await backend.respond("저녁이야?", ctx())
    assert result.text == "지금은 저녁이에요."
    assert (result.input_tokens, result.output_tokens) == (40, 15)  # cache reads not counted

    call = calls()[0]
    argv = call["argv"]
    assert argv[:3] == ["-p", "--output-format", "json"]
    assert argv[argv.index("--tools") + 1] == ""  # all built-in tools disabled
    assert "--strict-mcp-config" in argv
    assert argv[argv.index("--allowedTools") + 1] == "mcp__jarvis"
    assert argv[argv.index("--model") + 1] == "haiku"
    assert "자비스" in argv[argv.index("--system-prompt") + 1]
    assert "--resume" not in argv
    assert "저녁이야?" in call["stdin"]  # prompt goes through stdin, never argv
    assert call["cwd"] == str(tmp_path / "work")

    await backend.respond("그럼 내일은?", ctx())
    argv2 = calls()[1]["argv"]
    assert argv2[argv2.index("--resume") + 1] == "sess-123"

    backend.reset()
    await backend.respond("새 대화", ctx())
    assert "--resume" not in calls()[2]["argv"]


async def test_mcp_config_is_private_and_points_at_bridge(tmp_path, fake_claude):
    exe, _, _ = fake_claude
    backend = make(tmp_path, exe)
    cfg = json.loads(backend.mcp_config.read_text())
    server = cfg["mcpServers"]["jarvis"]
    assert server["args"] == ["-m", "jarvis.brain.mcp_bridge"]
    assert server["env"] == {"JARVIS_TOOLS_URL": "http://127.0.0.1:8765", "JARVIS_TOOLS_TOKEN": "tok"}
    assert backend.mcp_config.stat().st_mode & 0o077 == 0


async def test_login_error(tmp_path, fake_claude):
    exe, mode, _ = fake_claude
    mode.write_text("login")
    with pytest.raises(LLMError) as info:
        await make(tmp_path, exe).respond("x", ctx())
    assert "로그인" in info.value.user_message


async def test_usage_limit(tmp_path, fake_claude):
    exe, mode, _ = fake_claude
    mode.write_text("is_error")
    with pytest.raises(LLMError) as info:
        await make(tmp_path, exe).respond("x", ctx())
    assert "한도" in info.value.user_message


async def test_timeout_is_retryable(tmp_path, fake_claude):
    exe, mode, _ = fake_claude
    mode.write_text("slow")
    with pytest.raises(LLMRetryableError):
        await make(tmp_path, exe, timeout_sec=0.5).respond("x", ctx())


async def test_missing_binary(tmp_path):
    backend = make(tmp_path, tmp_path / "nope" / "claude")
    assert backend.availability() == "error"
    with pytest.raises(LLMError) as info:
        await backend.respond("x", ctx())
    assert "설치" in info.value.user_message


async def test_too_old_macos(tmp_path, fake_claude):
    exe, mode, _ = fake_claude
    mode.write_text("dyld")
    with pytest.raises(LLMError) as info:
        await make(tmp_path, exe).respond("x", ctx())
    assert "api" in info.value.user_message
