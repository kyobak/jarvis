"""Live world. Integrations arrive phase by phase; until then they report "disabled"."""

from __future__ import annotations

from typing import Any

from jarvis.core.config import Config
from jarvis.core.event_bus import EventBus
from jarvis.core.status import StatusBoard


class LiveWorld:
    def __init__(self, config: Config, bus: EventBus, status: StatusBoard) -> None:
        self.config = config
        self.bus = bus
        self.status = status

    async def start(self) -> None:
        await self.status.update(
            camera="off",
            integrations={"gmail": "disabled", "slack": "disabled", "spotify": "disabled"},
        )
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
