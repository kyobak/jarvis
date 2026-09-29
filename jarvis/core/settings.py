"""User-adjustable settings (settings screen), persisted as JSON over config defaults."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from jarvis.core.config import Config, HourRange
from jarvis.core.event_bus import EventBus

log = logging.getLogger(__name__)

BOOL_KEYS = (
    "voice_alerts",  # speak reminders / event alerts
    "greeting",  # welcome back on return
    "daily_briefing",  # first-seen-today briefing
    "drowsiness",  # drowsiness detection
    "event_pre_alert",  # N minutes before an event
    "event_start_alert",  # when an event starts
    "message_voice_alert",  # say when new mail/Slack arrives
    "camera_paused",  # privacy: camera fully released
    "camera_preview",  # show the camera image in the UI
)
HOUR_KEYS = ("quiet_hours", "drowsy_hours")


def defaults_from(config: Config) -> dict[str, Any]:
    fmt = lambda r: f"{r.start:%H:%M}-{r.end:%H:%M}"  # noqa: E731
    return {
        "voice_alerts": True,
        "greeting": True,
        "daily_briefing": True,
        "drowsiness": True,
        "event_pre_alert": True,
        "event_start_alert": True,
        "message_voice_alert": False,
        "camera_paused": False,
        "camera_preview": False,
        "quiet_hours": fmt(config.quiet_hours),
        "drowsy_hours": fmt(config.vision.active_hours),
        "pre_alert_min": config.calendar.pre_alert_min,
    }


class Settings:
    def __init__(self, bus: EventBus, config: Config, path: Path | None) -> None:
        self.bus = bus
        self.path = path
        self.values = defaults_from(config)
        if path and path.exists():
            try:
                stored = json.loads(path.read_text(encoding="utf-8"))
                self.values.update({k: v for k, v in stored.items() if k in self.values})
            except (OSError, ValueError):
                log.warning("ignoring unreadable settings file %s", path)

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    def hours(self, key: str) -> HourRange:
        return HourRange.parse(self.values[key])

    def in_quiet_hours(self, now: datetime) -> bool:
        return self.hours("quiet_hours").contains(now.time())

    def validate(self, key: str, value: Any) -> Any:
        if key not in self.values:
            raise KeyError(key)
        if key in BOOL_KEYS:
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be a boolean")
        elif key in HOUR_KEYS:
            HourRange.parse(str(value))
            value = str(value)
        elif key == "pre_alert_min":
            value = int(value)
            if not 0 <= value <= 120:
                raise ValueError("pre_alert_min must be 0–120")
        return value

    async def update(self, changes: dict[str, Any]) -> list[str]:
        """Apply valid changes; returns the keys that changed."""
        changed = []
        for key, value in changes.items():
            try:
                value = self.validate(key, value)
            except (KeyError, ValueError) as e:
                log.warning("rejected setting %s=%r: %s", key, value, e)
                continue
            if self.values[key] != value:
                self.values[key] = value
                changed.append(key)
        if changed:
            self._save()
            await self.publish()
        return changed

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.values, ensure_ascii=False, indent=2), encoding="utf-8")

    async def publish(self) -> None:
        await self.bus.publish("settings", dict(self.values))
