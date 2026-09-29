"""Single owner of the `status` event; modules update only their own fields."""

from __future__ import annotations

import copy
from typing import Any

from jarvis.core.event_bus import EventBus


class StatusBoard:
    def __init__(self, bus: EventBus, **initial: Any) -> None:
        self.bus = bus
        self.data: dict[str, Any] = {
            "mock": False,
            "dev": False,
            "user_name": "",
            "camera": "off",
            "mic": "off",
            "integrations": {},
            "llm": {"calls": 0, "tokens": 0, "limit": 0, "backend": "off"},
        }
        self._merge(initial)

    def _merge(self, fields: dict[str, Any]) -> None:
        for key, value in fields.items():
            if isinstance(value, dict) and isinstance(self.data.get(key), dict):
                self.data[key].update(value)
            else:
                self.data[key] = value

    async def update(self, **fields: Any) -> None:
        self._merge(fields)
        await self.publish()

    async def publish(self) -> None:
        await self.bus.publish("status", copy.deepcopy(self.data))
