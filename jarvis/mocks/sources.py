"""Fake player and inbox with the same interfaces as the real Spotify/Gmail/Slack sources."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from jarvis.core.timeutil import iso
from jarvis.mocks import data


class MockPlayer:
    name = "mock"

    def __init__(self) -> None:
        self.index = 0
        self.playing = True
        self.position_ms = 83_000
        self.at = time.monotonic()
        self.volume = 62
        self.uri: str | None = None

    def _pos(self) -> int:
        return self.position_ms + (int((time.monotonic() - self.at) * 1000) if self.playing else 0)

    def _jump(self, index: int) -> None:
        self.index = index % len(data.TRACKS)
        self.position_ms, self.at = 0, time.monotonic()

    async def state(self) -> dict[str, Any]:
        track = data.TRACKS[self.index]
        if self._pos() >= track["duration_ms"]:
            self._jump(self.index + 1)
            track = data.TRACKS[self.index]
        return {
            "title": track["title"], "artist": track["artist"], "album": track["album"],
            "duration_ms": track["duration_ms"], "progress_ms": self._pos(), "art_url": None,
            "art_hue": track["hue"], "is_playing": self.playing, "volume": self.volume, "uri": f"mock:{self.index}",
        }

    async def play(self) -> None:
        if not self.playing:
            self.position_ms, self.at, self.playing = self._pos(), time.monotonic(), True

    async def pause(self) -> None:
        if self.playing:
            self.position_ms, self.at, self.playing = self._pos(), time.monotonic(), False

    async def next(self) -> None:
        self._jump(self.index + 1)

    async def previous(self) -> None:
        self._jump(self.index - 1)

    async def set_volume(self, volume: int) -> None:
        self.volume = max(0, min(100, int(volume)))

    async def play_uri(self, uri: str) -> None:
        self.uri = uri
        self._jump(1)  # "Blue in Green": close enough to "잔잔한 재즈"
        self.playing = True


class MockSearch:
    async def find(self, query: str) -> dict[str, str]:
        return {"uri": f"mock:playlist:{query}", "name": query, "kind": "playlist"}


class MockInbox:
    mock = True

    def __init__(self, name: str, now: datetime) -> None:
        self.name = name
        self.box = data.messages(now)[name]
        self.expired = False

    def add(self, sender: str, subject: str, snippet: str, now: datetime) -> None:
        self.box["items"].append(
            {"id": f"{self.name}-{time.time_ns()}", "sender": sender, "subject": subject, "snippet": snippet, "received_at": iso(now)}
        )

    async def fetch(self) -> dict[str, Any]:
        if self.expired:
            from jarvis.integrations.oauth import AuthRequired

            raise AuthRequired("mock expiry")
        items = sorted(self.box["items"], key=lambda m: m["received_at"], reverse=True)
        return {"count": len(items), "items": items}
