"""In-process async pub/sub. Every module talks to others only through events."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

Handler = Callable[["Event"], Awaitable[None] | None]
WILDCARD = "*"


@dataclass(frozen=True, slots=True)
class Event:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_wire(self) -> dict[str, Any]:
        return {"type": self.type, "payload": self.payload}


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: Handler) -> Callable[[], None]:
        """Register a handler; returns an unsubscribe function."""
        self._handlers[event_type].append(handler)

        def unsubscribe() -> None:
            try:
                self._handlers[event_type].remove(handler)
            except ValueError:
                pass

        return unsubscribe

    async def publish(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        event = Event(event_type, payload or {})
        handlers = [*self._handlers.get(event_type, ()), *self._handlers.get(WILDCARD, ())]
        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                # One broken subscriber must not take down the others.
                log.exception("event handler failed for %s", event_type)
