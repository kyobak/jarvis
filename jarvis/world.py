"""Live world. Integrations arrive phase by phase; until then they report "disabled"."""

from __future__ import annotations

from typing import Any

from jarvis.core.config import Config
from jarvis.core.db import Database
from jarvis.core.event_bus import EventBus
from jarvis.core.timeutil import now


class LiveWorld:
    def __init__(self, config: Config, bus: EventBus, db: Database, dev: bool = False) -> None:
        self.config = config
        self.bus = bus
        self.db = db
        self.dev = dev

    async def start(self) -> None:
        usage = self.db.llm_usage(now(self.config.tz).date())
        await self.bus.publish(
            "status",
            {
                "mock": False,
                "dev": self.dev,
                "user_name": self.config.user_name,
                "camera": "off",
                "mic": "off",
                "integrations": {
                    "calendar": "disabled",
                    "gmail": "disabled",
                    "slack": "disabled",
                    "spotify": "disabled",
                    "claude": "disabled",
                },
                "llm": {
                    "calls": usage["calls"],
                    "tokens": usage["input_tokens"] + usage["output_tokens"],
                    "limit": self.config.llm.daily_token_limit,
                },
            },
        )
        await self.bus.publish("state", {"core": "idle"})
        await self.bus.publish("schedule", {"events": [], "synced_at": None, "offline": False})
        await self.bus.publish("reminders", {"items": []})
        await self.bus.publish(
            "messages",
            {
                "gmail": {"auth": "disabled", "count": 0, "items": []},
                "slack": {"auth": "disabled", "count": 0, "items": []},
            },
        )
        await self.bus.publish("now_playing", {"title": None})
        await self.bus.publish("focus", {"today_min": 0, "week": [], "session": None})

    async def stop(self) -> None:
        pass

    async def handle_dev(self, action: str, value: Any = None) -> None:
        if action == "state":
            await self.bus.publish("state", {"core": value})

    async def handle_ptt(self, down: bool) -> None:
        pass  # Voice loop arrives in Phase 2.

    async def handle_alert_ack(self) -> None:
        await self.bus.publish("state", {"core": "idle"})
