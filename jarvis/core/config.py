"""Config loading: config.yaml (optional) layered over built-in defaults."""

from __future__ import annotations

import os
import re
import sys
from datetime import time
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, Field, field_validator

REPO_ROOT = Path(__file__).resolve().parents[2]

_HOURS_RE = re.compile(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$")


class HourRange(BaseModel):
    """A daily window like "09:00-02:00"; may wrap past midnight."""

    start: time
    end: time

    @classmethod
    def parse(cls, value: str) -> "HourRange":
        m = _HOURS_RE.match(value.strip())
        if not m:
            raise ValueError(f"invalid hour range: {value!r} (expected HH:MM-HH:MM)")
        h1, m1, h2, m2 = (int(g) for g in m.groups())
        return cls(start=time(h1 % 24, m1), end=time(h2 % 24, m2))

    def contains(self, t: time) -> bool:
        if self.start <= self.end:
            return self.start <= t < self.end
        return t >= self.start or t < self.end


def _hour_range(v: object) -> HourRange:
    if isinstance(v, HourRange):
        return v
    if isinstance(v, dict):
        return HourRange(**v)
    return HourRange.parse(str(v))


LLMBackendName = Literal["openai_compat", "api", "claude_code", "off", "mock"]
ProviderName = Literal["gemini", "groq", "openrouter", "github", "ollama", "custom"]
STTEngineName = Literal["auto", "faster_whisper", "whisper_cpp", "apple", "mock"]


class OpenAICompatConfig(BaseModel):
    """Any OpenAI-compatible chat API (Gemini, Groq, OpenRouter, GitHub Models, Ollama, …)."""

    provider: ProviderName = "gemini"
    model: str | None = None  # None = the provider preset's default
    base_url: str | None = None  # None = the provider preset's URL
    api_key_env: str | None = None  # None = the provider preset's variable
    max_tokens: int = 1024  # thinking models spend part of this before answering
    extra_body: dict[str, Any] = Field(default_factory=dict)


class LLMConfig(BaseModel):
    # openai_compat: a free-tier API such as Gemini (falls back to off without a key);
    # api: Anthropic API (falls back to off without ANTHROPIC_API_KEY);
    # claude_code: `claude -p` on a Pro/Max login (macOS 13+); off: local intents only.
    backend: LLMBackendName = "openai_compat"
    # Schedule titles (and later mail/Slack content) go to the model only when this is true.
    # None = true for Claude backends, false for openai_compat (free tiers may train on inputs).
    send_personal_data: bool | None = None
    openai_compat: OpenAICompatConfig = Field(default_factory=OpenAICompatConfig)
    default_model: str = "claude-haiku-4-5"
    smart_model: str = "claude-sonnet-5-5"
    claude_code_model: str = "haiku"
    claude_code_path: str = "claude"
    max_tokens: int = 300
    daily_token_limit: int = 200_000
    history_turns: int = 6
    history_reset_min: int = 5
    timeout_sec: float = 30

    def personal_data_allowed(self, backend: str) -> bool:
        if self.send_personal_data is not None:
            return self.send_personal_data
        return backend in ("api", "claude_code", "mock")


class VoiceConfig(BaseModel):
    wake_word: str = "hey_jarvis"
    wake_threshold: float = 0.5
    tts_voice: str = "Yuna"
    tts_rate: int = 190
    stt_engine: STTEngineName = "auto"
    stt_model: str = "small"
    input_device: str | int | None = None
    silence_sec: float = 0.8
    max_utterance_sec: float = 10.0
    no_speech_timeout_sec: float = 5.0


class VisionConfig(BaseModel):
    camera_index: int = 0
    greet_after_absence_min: int = 10
    drowsy_ear_ratio: float = 0.75
    drowsy_seconds: float = 2.5
    active_hours: HourRange = Field(default_factory=lambda: HourRange.parse("09:00-02:00"))

    @field_validator("active_hours", mode="before")
    @classmethod
    def _parse_active(cls, v: object) -> HourRange:
        return _hour_range(v)


class CalendarConfig(BaseModel):
    google_calendar_ids: list[str] = Field(default_factory=lambda: ["primary"])
    pre_alert_min: int = 10


class SpotifyConfig(BaseModel):
    aliases: dict[str, str] = Field(default_factory=dict)


class MessagesConfig(BaseModel):
    gmail_poll_min: int = 5
    slack_poll_min: int = 3


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8765

    @field_validator("host")
    @classmethod
    def _loopback_only(cls, v: str) -> str:
        if v not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("server must bind to loopback only")
        return v


class UIConfig(BaseModel):
    fullscreen: bool = True
    target_fps: int = 30


class Config(BaseModel):
    user_name: str = "재원"
    timezone: str = "Asia/Seoul"
    llm: LLMConfig = Field(default_factory=LLMConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    vision: VisionConfig = Field(default_factory=VisionConfig)
    quiet_hours: HourRange = Field(default_factory=lambda: HourRange.parse("02:00-08:00"))
    calendar: CalendarConfig = Field(default_factory=CalendarConfig)
    spotify: SpotifyConfig = Field(default_factory=SpotifyConfig)
    messages: MessagesConfig = Field(default_factory=MessagesConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    ui: UIConfig = Field(default_factory=UIConfig)

    @field_validator("quiet_hours", mode="before")
    @classmethod
    def _parse_quiet(cls, v: object) -> HourRange:
        return _hour_range(v)

    @field_validator("timezone")
    @classmethod
    def _valid_tz(cls, v: str) -> str:
        ZoneInfo(v)
        return v

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def default_data_dir() -> Path:
    override = os.environ.get("JARVIS_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Jarvis"
    return Path.home() / ".local" / "share" / "jarvis"


def load_config(path: Path | None = None) -> Config:
    """Load config from `path`, else ./config.yaml at the repo root, else defaults."""
    candidate = path or (REPO_ROOT / "config.yaml")
    if candidate.exists():
        data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
        return Config.model_validate(data)
    if path is not None:
        raise FileNotFoundError(path)
    return Config()
