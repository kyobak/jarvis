"""Latest-value cache for "sticky" event types so new UI clients get a full picture."""

from __future__ import annotations

from typing import Any

from jarvis.core.event_bus import WILDCARD, Event, EventBus

# Types whose latest payload fully describes that part of the UI.
STICKY_TYPES = (
    "status",
    "state",
    "schedule",
    "reminders",
    "messages",
    "now_playing",
    "focus",
    "drowsiness",
    "settings",
    "presence",
)


class StateStore:
    def __init__(self, bus: EventBus) -> None:
        self._latest: dict[str, dict[str, Any]] = {}
        bus.subscribe(WILDCARD, self._on_event)

    def _on_event(self, event: Event) -> None:
        if event.type in STICKY_TYPES:
            self._latest[event.type] = event.payload

    def get(self, event_type: str) -> dict[str, Any] | None:
        return self._latest.get(event_type)

    def snapshot(self) -> list[Event]:
        """Sticky events in a stable order, for replay to a newly connected client."""
        return [Event(t, self._latest[t]) for t in STICKY_TYPES if t in self._latest]
