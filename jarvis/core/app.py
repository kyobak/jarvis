"""Wires config, storage, brain, voice, vision, and the integrations together."""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime
from typing import Any

import httpx2

from jarvis.brain.backends.base import LLMBackend
from jarvis.brain.brain import Brain
from jarvis.brain.context import Context
from jarvis.brain.tools import Tool, ToolRegistry, schema
from jarvis.core.announcer import Announcer
from jarvis.core.config import Config, default_data_dir
from jarvis.core.core_state import CoreStateMachine
from jarvis.core.db import Database
from jarvis.core.event_bus import Event, EventBus
from jarvis.core.presence import Presence
from jarvis.core.secrets import SecretStore
from jarvis.core.settings import Settings
from jarvis.core.state import StateStore
from jarvis.core.status import StatusBoard
from jarvis.integrations.oauth import OAuthClient
from jarvis.skills.calendar import CalendarService
from jarvis.skills.focus import FocusService
from jarvis.skills.greeter import Greeter
from jarvis.skills.messages import MessagesService
from jarvis.skills.music import MusicService
from jarvis.skills.reminders import ReminderService

log = logging.getLogger(__name__)


class LiveWorld:
    """Real mode has no fake data; only the visual state override is available with --dev."""

    def __init__(self, bus: EventBus) -> None:
        self.bus = bus

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def handle_dev(self, action: str, value: Any = None) -> None:
        if action == "state":
            await self.bus.publish("state", {"core": value})


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
        vision: str | None = None,
        enable_voice: bool = True,
    ) -> None:
        self.config = config
        self.mock = mock
        self.dev = dev or mock
        self.voice_mode = voice or ("mock" if mock else "real")
        # --mock fakes hardware and integrations; the AI stays whatever config says
        # (it falls back to `off` without a key).
        self.llm_backend_name = llm or config.llm.backend
        self.vision_mode = vision or ("mock" if mock else "real")
        self.stt_name = stt or ("mock" if self.voice_mode == "mock" else config.voice.stt_engine)
        data_dir = default_data_dir()

        self.bus = EventBus()
        self.store = StateStore(self.bus)
        # Mock runs never touch the real database (reminders, focus history, usage).
        self.db = Database(db_path or (":memory:" if mock else data_dir / "jarvis.db"))
        self.status = StatusBoard(self.bus, mock=mock, dev=self.dev, user_name=config.user_name)
        self.core = CoreStateMachine(self.bus)
        self.settings = Settings(self.bus, config, None if mock else data_dir / "settings.json")
        self.presence = Presence(self.bus)
        self.announcer = Announcer(self.bus, self.settings, self.presence, self.clock)
        self.tool_token = secrets.token_urlsafe(24)
        self.tools = ToolRegistry()
        self._register_status_tool()
        self.brain = Brain(config, self.store, self.db, self.status, self._make_backend(), clock=self.clock)
        self.personal_ok = config.llm.personal_data_allowed(self.brain.backend.name)

        # Integrations: one HTTP client, tokens in the Keychain, OAuth via /auth/<name>.
        self.http = httpx2.AsyncClient(timeout=20)
        self.secrets = SecretStore(None if mock else data_dir / "secrets.json", use_keyring=not mock)
        self.oauth: dict[str, OAuthClient] = {}
        self._setup_oauth(data_dir)

        self.reminders = ReminderService(self.db, self.bus, self.announcer, self.clock)
        google = self.oauth.get("google")
        self.calendar = CalendarService(
            self.db, self.bus, self.status, self.announcer, self.presence, self.settings, self.clock,
            source=self._calendar_source() if google and google.has_token() else None,
            configured=google is not None,
        )
        self.focus = FocusService(self.db, self.bus, self.announcer, self.clock)
        self.messages = self._make_messages()
        self.music = self._make_music()
        self.greeter = Greeter(
            self.announcer, self.settings, self.clock, config.user_name,
            upcoming=self.calendar.upcoming, unread=self.messages.unread,
            today_events=lambda now: self.calendar.between(now.replace(hour=0, minute=0), now.replace(hour=23, minute=59)),
        )
        from jarvis.vision.enroll import profile_path
        from jarvis.vision.service import VisionService

        self.vision = VisionService(
            config, self.bus, self.status, self.presence, self.announcer, self.settings,
            self.focus, self.greeter, self.clock, self.vision_mode, profile_path(),
        )

        # Local fast paths, tried in order before the LLM.
        for name, skill in (("reminders", self.reminders), ("calendar", self.calendar), ("focus", self.focus),
                            ("music", self.music), ("messages", self.messages)):
            self.brain.add_handler(name, skill)
        self.reminders.register_tools(self.tools)
        self.focus.register_tools(self.tools)
        self.music.register_tools(self.tools)
        if self.personal_ok:  # tools that return schedule titles or message content
            self.calendar.register_tools(self.tools)
            self.messages.register_tools(self.tools)

        if mock:
            from jarvis.mocks.world import MockWorld

            self.world: Any = MockWorld(self)
        else:
            self.world = LiveWorld(self.bus)

        self.voice = self._make_voice() if enable_voice else None
        if self.voice:
            self.announcer.speaker = self.voice.announce
            self.voice.on_speech_start.append(self.music.duck)
            self.voice.on_speech_end.append(self.music.unduck)
        self.vision.on_wake_alarm.append(self.music.wake_up)
        self.focus.on_nap_end.append(self.music.wake_up)
        self.bus.subscribe("settings", self._on_settings)
        self._camera_paused = self.settings["camera_paused"]

    def clock(self) -> datetime:
        return datetime.now(self.config.tz)

    # ---- construction helpers -------------------------------------------------

    def _register_status_tool(self) -> None:
        async def get_status(_: dict[str, Any]) -> dict[str, Any]:
            ctx = Context.build(self.store, self.clock(), self.config.user_name)
            return ctx.status_summary()

        self.tools.register(
            Tool(
                "get_status",
                "카메라·마이크·연동(캘린더, Gmail, Slack, Spotify, AI) 상태와 오늘 AI 사용량을 조회한다.",
                schema(),
                get_status,
            )
        )

    def _setup_oauth(self, data_dir) -> None:
        if self.mock:
            return
        from jarvis.integrations.google import make_google_oauth
        from jarvis.integrations.spotify import make_spotify_oauth

        base = f"http://{self.config.server.host}:{self.config.server.port}/callback"
        google = make_google_oauth(data_dir / "google_client_secret.json", self.secrets, self.http, f"{base}/google")
        if google:
            self.oauth["google"] = google
        spotify_id = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
        if spotify_id:
            self.oauth["spotify"] = make_spotify_oauth(spotify_id, self.secrets, self.http, f"{base}/spotify")

    def _calendar_source(self):
        from jarvis.integrations.google import GoogleCalendarSource

        return GoogleCalendarSource(self.oauth["google"], self.config.calendar.google_calendar_ids, self.config.tz)

    def _make_messages(self) -> MessagesService:
        mc = self.config.messages
        poll = {"gmail": mc.gmail_poll_min * 60, "slack": mc.slack_poll_min * 60}
        if self.mock:
            from jarvis.mocks.sources import MockInbox

            now = self.clock()
            sources = {"gmail": MockInbox("gmail", now), "slack": MockInbox("slack", now)}
            configured = {"gmail": True, "slack": True}
            poll = {"gmail": 60, "slack": 60}
        else:
            from jarvis.integrations.gmail import GmailSource
            from jarvis.integrations.slack import SlackSource

            google = self.oauth.get("google")
            slack_token = os.environ.get("SLACK_USER_TOKEN", "").strip() or self.secrets.get("slack_user_token")
            sources = {
                "gmail": GmailSource(google) if google and google.has_token() else None,
                "slack": SlackSource(slack_token, self.http) if slack_token else None,
            }
            configured = {"gmail": google is not None, "slack": bool(slack_token)}
        summarizer = self.brain.summarize if self.personal_ok else None
        return MessagesService(self.bus, self.status, self.announcer, self.presence, self.settings,
                               sources, poll, configured, summarizer)

    def _make_music(self) -> MusicService:
        aliases = self.config.spotify.aliases
        if self.mock:
            from jarvis.mocks.sources import MockPlayer, MockSearch

            return MusicService(self.bus, self.status, MockPlayer(), aliases, MockSearch(), True)
        from jarvis.integrations.spotify import AppleScriptSpotify, SpotifySearch

        player = AppleScriptSpotify() if AppleScriptSpotify.available() else None
        oauth = self.oauth.get("spotify")
        search = SpotifySearch(oauth) if oauth and oauth.has_token() else None
        return MusicService(self.bus, self.status, player, aliases, search, oauth is not None)

    def _make_backend(self) -> LLMBackend:
        from jarvis.brain.backends.simple import MockBackend, OffBackend

        name = self.llm_backend_name
        backend: LLMBackend
        if name == "openai_compat":
            from jarvis.brain.backends.openai_compat import OpenAICompatBackend

            backend = OpenAICompatBackend(self.config.llm, self.tools, self.config.user_name)
            problem = backend.problem()
        elif name == "api":
            from jarvis.brain.backends.api import ApiBackend

            backend = ApiBackend(self.config.llm, self.tools, self.config.user_name)
            problem = None if os.environ.get("ANTHROPIC_API_KEY") else "ANTHROPIC_API_KEY is not set"
        elif name == "claude_code":
            from jarvis.brain.backends.claude_code import ClaudeCodeBackend, ToolBridge

            server = self.config.server
            bridge = ToolBridge(f"http://{server.host}:{server.port}", self.tool_token)
            workdir = default_data_dir() / "claude-workdir"
            return ClaudeCodeBackend(self.config.llm, bridge, self.config.user_name, workdir)
        elif name == "mock":
            return MockBackend()
        else:
            return OffBackend()

        if problem:
            # Local commands are the foundation; an unconfigured AI simply means "off".
            log.info("%s backend not configured (%s); running with local commands only", name, problem)
            return OffBackend()
        return backend

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
            "starting jarvis (mock=%s, voice=%s, vision=%s, llm=%s, stt=%s)",
            self.mock, self.voice_mode, self.vision_mode, self.brain.backend.name, self.stt_name,
        )
        await self.status.publish()
        await self.core.publish_current()
        await self.settings.publish()
        await self.reminders.start()
        if self.mock:
            from jarvis.mocks.data import seed_reminders

            await seed_reminders(self.reminders, self.clock())
        await self.calendar.start(mock=self.mock)
        await self.focus.publish()
        await self.messages.start()
        await self.music.start()
        await self.world.start()
        await self.brain.publish_usage()
        if self.brain.backend.availability() == "error":
            log.warning("LLM backend %s is not usable; check its setup", self.brain.backend.name)
        await self.vision.start()
        if self.voice:
            await self.voice.start()

    async def stop(self) -> None:
        if self.voice:
            await self.voice.stop()
        for service in (self.vision, self.music, self.messages, self.calendar, self.reminders, self.world):
            try:
                await service.stop()
            except Exception:
                log.exception("stopping %s failed", type(service).__name__)
        await self.http.aclose()
        self.db.close()

    async def oauth_connected(self, name: str) -> None:
        """A provider finished its browser flow: start the integrations that use it."""
        if name == "google":
            from jarvis.integrations.gmail import GmailSource

            await self.calendar.connected(self._calendar_source())
            await self.messages.connected("gmail", GmailSource(self.oauth["google"]))
        elif name == "spotify":
            from jarvis.integrations.spotify import SpotifySearch

            self.music.search = SpotifySearch(self.oauth["spotify"])

    async def _on_settings(self, event: Event) -> None:
        paused = bool(event.payload.get("camera_paused"))
        if paused != self._camera_paused:
            self._camera_paused = paused
            await self.vision.set_paused(paused)

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
            await self.announcer.clear(payload.get("id"))
        elif kind == "reminder_cancel":
            await self.reminders.cancel(int(payload.get("id", 0)))
        elif kind == "settings":
            changes = payload.get("changes")
            if isinstance(changes, dict):
                await self.settings.update(changes)
        elif kind == "music":
            action = str(payload.get("action", ""))
            if action in ("play", "pause", "next", "previous"):
                await self.music.control(action)
        elif kind == "dev":
            if not self.dev:
                log.warning("ignoring dev command outside dev mode")
                return
            await self.world.handle_dev(str(payload.get("action")), payload.get("value"))
        else:
            log.debug("unknown client message type %r", kind)
