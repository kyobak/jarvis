"""One place for proactive notices: shows the alert card and, when appropriate, speaks.

Rules: no speech during quiet hours or with voice alerts off; while the owner is away,
notices queue up and are summarised on return; with only a stranger present, personal
notices are spoken generically.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Awaitable, Callable

from jarvis.core.event_bus import EventBus
from jarvis.core.presence import Presence
from jarvis.core.settings import Settings

log = logging.getLogger(__name__)

Speaker = Callable[[str, str], Awaitable[None]]  # (text, sound)


class Announcer:
    def __init__(self, bus: EventBus, settings: Settings, presence: Presence, clock: Callable[[], datetime]) -> None:
        self.bus = bus
        self.settings = settings
        self.presence = presence
        self.clock = clock
        self.speaker: Speaker | None = None
        self.missed: list[str] = []
        self._seq = 0

    async def notify(
        self,
        kind: str,
        title: str,
        body: str = "",
        say: str | None = None,
        level: int = 1,
        personal: bool = True,
        sound: str = "Glass",
        force_voice: bool = False,
    ) -> int:
        """Show an alert card and maybe speak. `force_voice` ignores quiet hours (drowsiness, wake-up)."""
        self._seq += 1
        show_title = title if (self.presence.owner_here or not personal) else "알림이 있어요"
        await self.bus.publish(
            "alert",
            {"id": self._seq, "kind": kind, "level": level, "title": show_title, "body": body if show_title == title else "", "active": True},
        )
        if not self.presence.anyone_here and kind != "drowsy":
            self.missed.append(title)
            return self._seq
        if say is None or self.speaker is None:
            return self._seq
        if not force_voice and (not self.settings["voice_alerts"] or self.settings.in_quiet_hours(self.clock())):
            log.info("alert shown silently (quiet hours or voice alerts off): %s", kind)
            return self._seq
        text = say if (self.presence.owner_here or not personal) else "알림이 있어요. 확인해 주세요."
        await self.speaker(text, sound)
        return self._seq

    async def clear(self, alert_id: int | None = None) -> None:
        await self.bus.publish("alert", {"id": alert_id or self._seq, "active": False})

    def take_missed(self) -> list[str]:
        missed, self.missed = self.missed, []
        return missed
