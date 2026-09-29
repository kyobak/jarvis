"""Who is at the desk. Vision updates it; without a camera it stays "unknown" (treated as present)."""

from __future__ import annotations

from datetime import datetime

from jarvis.core.event_bus import EventBus

STATES = ("unknown", "present", "stranger", "away")


class Presence:
    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self.state = "unknown"
        self.since: datetime | None = None

    @property
    def owner_here(self) -> bool:
        """Personal content may be spoken."""
        return self.state in ("unknown", "present")

    @property
    def anyone_here(self) -> bool:
        return self.state != "away"

    async def set(self, state: str, at: datetime) -> str:
        """Returns the previous state."""
        if state not in STATES:
            raise ValueError(state)
        previous = self.state
        if state != previous:
            self.state = state
            self.since = at
            await self.bus.publish("presence", {"state": state, "previous": previous, "since": at.isoformat()})
        return previous
