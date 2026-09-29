"""Wires config, bus, storage, brain, voice, and the active world together."""

from __future__ import annotations

import logging
import os
import secrets
from typing import Any

from jarvis.brain.backends.base import LLMBackend
from jarvis.brain.brain import Brain
from jarvis.brain.context import Context
from jarvis.brain.tools import Tool, ToolRegistry, schema
from jarvis.core.config import Config, default_data_dir
from jarvis.core.core_state import CoreStateMachine
from jarvis.core.db import Database
from jarvis.core.event_bus import EventBus
from jarvis.core.state import StateStore
from jarvis.core.status import StatusBoard

log = logging.getLogger(__name__)


class JarvisApp:
    def __init__(
        self,
        config: Config,
        *,
        mock: bool,
        dev: bool = False,
        db_path: str | None = None,
        voice: str | None = None,
        llm: str | None = None,
        stt: str | None = None,
        enable_voice: bool = True,
    ) -> None:
        self.config = config
        self.mock = mock
        self.dev = dev or mock
        self.voice_mode = voice or ("mock" if mock else "real")
        self.llm_backend_name = llm or ("mock" if mock else config.llm.backend)
        self.stt_name = stt or ("mock" if self.voice_mode == "mock" else config.voice.stt_engine)

        self.bus = EventBus()
        self.store = StateStore(self.bus)
        self.db = Database(db_path or default_data_dir() / "jarvis.db")
        self.status = StatusBoard(self.bus, mock=mock, dev=self.dev, user_name=config.user_name)
        self.core = CoreStateMachine(self.bus)
        self.tool_token = secrets.token_urlsafe(24)
        self.tools = ToolRegistry()
        self._register_tools()

        self.brain = Brain(config, self.store, self.db, self.status, self._make_backend())

        if mock:
            from jarvis.mocks.world import MockWorld

            self.world = MockWorld(config, self.bus, self.status)
        else:
            from jarvis.world import LiveWorld

            self.world = LiveWorld(config, self.bus, self.status)

        self.voice = self._make_voice() if enable_voice else None

    # ---- construction helpers -------------------------------------------------

    def _register_tools(self) -> None:
        async def get_status(_: dict[str, Any]) -> dict[str, Any]:
            ctx = Context.build(self.store, self.brain.clock(), self.config.user_name)
            return ctx.status_summary()

        self.tools.register(
            Tool(
                "get_status",
                "카메라·마이크·연동(캘린더, Gmail, Slack, Spotify, AI) 상태와 오늘 AI 사용량을 조회한다.",
                schema(),
                get_status,
            )
        )

    def _make_backend(self) -> LLMBackend:
        name = self.llm_backend_name
        if name == "api":
            if not os.environ.get("ANTHROPIC_API_KEY"):
                # Local commands are the foundation; the API is an optional add-on.
                log.info("no ANTHROPIC_API_KEY; running with local commands only (llm off)")
                name = "off"
            else:
                from jarvis.brain.backends.api import ApiBackend

                return ApiBackend(self.config.llm, self.tools, self.config.user_name)
        if name == "claude_code":
            from jarvis.brain.backends.claude_code import ClaudeCodeBackend, ToolBridge

            server = self.config.server
            bridge = ToolBridge(f"http://{server.host}:{server.port}", self.tool_token)
            workdir = default_data_dir() / "claude-workdir"
            return ClaudeCodeBackend(self.config.llm, bridge, self.config.user_name, workdir)
        if name == "mock":
            from jarvis.brain.backends.simple import MockBackend

            return MockBackend()
        from jarvis.brain.backends.simple import OffBackend

        return OffBackend()

    def _make_voice(self):
        from jarvis.voice import stt as stt_module
        from jarvis.voice.loop import MockCapture, VoiceLoop

        vc = self.config.voice
        stt_engine = stt_module.make_stt(self.stt_name, vc.stt_model)
        if self.voice_mode == "mock":
            from jarvis.voice.audio import MockMic
            from jarvis.voice.tts import MockTTS

            return VoiceLoop(
                vc, self.bus, self.core, self.status, self.brain,
                mic=MockMic(), stt=stt_engine, tts=MockTTS(), capture_factory=MockCapture,
            )

        from jarvis.voice.audio import MicStream
        from jarvis.voice.tts import MockTTS, SayTTS
        from jarvis.voice.wakeword import make_wake_detector

        tts = SayTTS(vc.tts_voice, vc.tts_rate) if SayTTS.available() else MockTTS()
        if isinstance(tts, MockTTS):
            log.warning("`say` not found; replies will be shown but not spoken")
        return VoiceLoop(
            vc, self.bus, self.core, self.status, self.brain,
            mic=MicStream(vc.input_device), stt=stt_engine, tts=tts,
            wake=make_wake_detector(vc.wake_word, vc.wake_threshold),
        )

    # ---- lifecycle -----------------------------------------------------------------

    async def start(self) -> None:
        log.info(
            "starting jarvis (mock=%s, dev=%s, voice=%s, llm=%s, stt=%s)",
            self.mock, self.dev, self.voice_mode, self.llm_backend_name, self.stt_name,
        )
        await self.status.publish()
        await self.core.publish_current()
        await self.world.start()
        await self.brain.publish_usage()
        if self.brain.backend.availability() == "error":
            hint = {
                "claude_code": "install Claude Code and log in (needs macOS 13+), or set llm.backend to api/off",
                "api": "set ANTHROPIC_API_KEY in .env, or set llm.backend to claude_code/off",
            }.get(self.brain.backend.name, "")
            log.warning("LLM backend %s is not usable: %s", self.brain.backend.name, hint)
        if self.voice:
            await self.voice.start()

    async def stop(self) -> None:
        if self.voice:
            await self.voice.stop()
        await self.world.stop()
        self.db.close()

    async def handle_client(self, message: dict[str, Any]) -> None:
        """Messages sent from the UI over the WebSocket."""
        kind = message.get("type")
        payload = message.get("payload") or {}
        if kind == "ptt":
            if payload.get("down") and self.voice:
                await self.voice.push_to_talk()
        elif kind == "text":
            text = str(payload.get("text", "")).strip()[:300]
            if text and self.voice:
                await self.voice.say_text(text)
        elif kind == "alert_ack":
            await self.world.handle_alert_ack()
        elif kind == "dev":
            if not self.dev:
                log.warning("ignoring dev command outside dev mode")
                return
            await self.world.handle_dev(str(payload.get("action")), payload.get("value"))
        else:
            log.debug("unknown client message type %r", kind)
