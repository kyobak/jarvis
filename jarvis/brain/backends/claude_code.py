"""Claude Code backend: runs `claude -p` on the user's Pro/Max login (no API billing).

Built-in tools are disabled (`--tools ""`); the only tools are Jarvis's own, served by
`jarvis.brain.mcp_bridge` over MCP. Each call runs in an empty working directory so no
project instructions leak in. Follow-ups continue the same session via `--resume`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jarvis.brain.backends.base import LLMError, LLMResult, LLMRetryableError
from jarvis.brain.context import Context
from jarvis.brain.prompts import system_prompt, user_turn
from jarvis.core.config import LLMConfig

log = logging.getLogger(__name__)

MCP_SERVER_NAME = "jarvis"
LOGIN_HINTS = ("login", "log in", "/login", "not logged", "authenticat", "api key", "oauth", "credential")


@dataclass(frozen=True)
class ToolBridge:
    """Where the MCP bridge process reaches the running Jarvis server."""

    url: str
    token: str


class ClaudeCodeBackend:
    name = "claude_code"
    label = "Claude·구독"

    def __init__(self, config: LLMConfig, bridge: ToolBridge, user_name: str, workdir: Path) -> None:
        self.config = config
        self.bridge = bridge
        self.system = system_prompt(user_name)
        self.workdir = workdir
        self.session_id: str | None = None
        self.mcp_config = self._write_mcp_config()

    def _write_mcp_config(self) -> Path:
        self.workdir.mkdir(parents=True, exist_ok=True)
        path = self.workdir / "jarvis-mcp.json"
        config = {
            "mcpServers": {
                MCP_SERVER_NAME: {
                    "command": sys.executable,
                    "args": ["-m", "jarvis.brain.mcp_bridge"],
                    "env": {"JARVIS_TOOLS_URL": self.bridge.url, "JARVIS_TOOLS_TOKEN": self.bridge.token},
                }
            }
        }
        # The file holds a per-run token; keep it private.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(config, f)
        return path

    def availability(self) -> str:
        return "ok" if shutil.which(self.config.claude_code_path) else "error"

    def reset(self) -> None:
        self.session_id = None

    def command(self) -> list[str]:
        cmd = [
            self.config.claude_code_path,
            "-p",
            "--output-format", "json",
            "--model", self.config.claude_code_model,
            "--system-prompt", self.system,
            "--tools", "",
            "--strict-mcp-config",
            "--mcp-config", str(self.mcp_config),
            "--allowedTools", f"mcp__{MCP_SERVER_NAME}",
        ]
        if self.session_id:
            cmd += ["--resume", self.session_id]
        return cmd

    async def respond(self, utterance: str, ctx: Context) -> LLMResult:
        prompt = user_turn(ctx, utterance)
        try:
            proc = await asyncio.create_subprocess_exec(
                *self.command(),
                cwd=self.workdir,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as e:
            raise LLMError(str(e), "Claude Code가 설치되어 있지 않아요. 설치 안내를 확인해 주세요.") from e

        try:
            out, err = await asyncio.wait_for(proc.communicate(prompt.encode()), self.config.timeout_sec)
        except asyncio.TimeoutError as e:
            proc.kill()
            await proc.wait()
            raise LLMRetryableError("claude -p timed out") from e

        data = self._parse(out)
        if proc.returncode != 0 or data is None or data.get("is_error"):
            detail = (data or {}).get("result") or err.decode(errors="replace") or out.decode(errors="replace")
            self._raise_for(detail.strip())

        assert data is not None
        if data.get("session_id"):
            self.session_id = data["session_id"]
        usage = data.get("usage") or {}
        text = str(data.get("result") or "").strip() or "죄송해요, 뭐라고 답해야 할지 모르겠어요."
        # Cache reads are excluded: they dominate every resumed turn but cost a fraction of
        # fresh input, and counting them would exhaust the daily limit after a few dozen questions.
        return LLMResult(
            text,
            input_tokens=int(usage.get("input_tokens", 0)) + int(usage.get("cache_creation_input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
        )

    @staticmethod
    def _parse(out: bytes) -> dict[str, Any] | None:
        text = out.decode(errors="replace").strip()
        if not text:
            return None
        # json mode prints a single object; tolerate stray lines before it.
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def _raise_for(self, detail: str) -> None:
        log.error("claude -p failed: %s", detail[:500])
        lowered = detail.lower()
        if "newer than running os" in lowered or "dyld" in lowered or "bad cpu type" in lowered:
            raise LLMError(detail, "이 macOS에서는 Claude Code가 실행되지 않아요. 설정에서 AI 연결을 api로 바꿔 주세요.")
        if any(h in lowered for h in LOGIN_HINTS):
            raise LLMError(detail, "Claude Code 로그인이 필요해요. 터미널에서 claude를 한 번 실행해 로그인해 주세요.")
        if "usage limit" in lowered or "rate limit" in lowered or "limit reached" in lowered:
            raise LLMError(detail, "구독 사용량 한도에 도달했어요. 잠시 후에 다시 물어봐 주세요.")
        if "session" in lowered and self.session_id:
            # A stale --resume id: start fresh next time.
            self.session_id = None
        if any(h in lowered for h in ("network", "econn", "timed out", "overloaded", "503", "529")):
            raise LLMRetryableError(detail)
        raise LLMError(detail)
