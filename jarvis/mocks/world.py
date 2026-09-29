"""Mock world: seeds demo data into the real services and handles developer shortcuts.

The services themselves are real; only their data sources are fake (see mocks/sources.py),
so every feature can be exercised without hardware or accounts.
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from jarvis.mocks import data
from jarvis.mocks.sources import MockInbox

if TYPE_CHECKING:
    from jarvis.core.app import JarvisApp

CORE_STATES = ("idle", "listening", "thinking", "speaking", "alert", "offline")


class MockWorld:
    def __init__(self, app: "JarvisApp") -> None:
        self.app = app
        self.bus = app.bus
        self._tasks: list[asyncio.Task] = []

    def now(self) -> datetime:
        return self.app.clock()

    async def start(self) -> None:
        await self.app.status.update(camera="mock")
        await self.app.calendar.set_events(data.schedule(self.now()))
        self._seed_focus_history()
        await self.app.focus.publish()
        self._tasks.append(asyncio.create_task(self._inbox_loop(), name="mock-inbox"))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()

    def _seed_focus_history(self) -> None:
        db = self.app.db
        now = self.now()
        for day in data.focus_week(now):
            start = datetime.fromisoformat(day["date"] + "T10:00:00").replace(tzinfo=now.tzinfo)
            if start > now:
                start = now - timedelta(hours=4)
            with db.conn:
                db.conn.execute(
                    "INSERT INTO focus_sessions (start_utc, end_utc, planned_min, actual_min) VALUES (?, ?, ?, ?)",
                    (start.isoformat(), (start + timedelta(minutes=day["min"])).isoformat(), day["min"], day["min"]),
                )

    async def _inbox_loop(self) -> None:
        while True:
            await asyncio.sleep(random.uniform(240, 420))
            await self.incoming_message()

    async def incoming_message(self) -> None:
        source, sender, subject, snippet = next(data.INCOMING)
        inbox = self.app.messages.sources.get(source)
        if isinstance(inbox, MockInbox):
            inbox.add(sender, subject, snippet, self.now())
            await self.app.messages.refresh(source)

    async def handle_dev(self, action: str, value: Any = None) -> None:
        app = self.app
        if action == "state" and value in CORE_STATES:
            # Visual check only: bypasses the state machine until the next real change.
            await self.bus.publish("state", {"core": value})
        elif action == "reminder":
            text = "지금은 빨래 꺼내기 할 차례예요."
            await app.announcer.notify("reminder", text, say=text)
        elif action == "event":
            await app.announcer.notify("event", "10분 뒤에 UMC 스터디 일정이 있어요.", body="준비물: 발표 자료",
                                       say="10분 뒤에 UMC 스터디 일정이 있어요.")
        elif action == "drowsy":
            app.vision.simulate_drowsy(2 if value == 2 else 1)
        elif action == "away":
            app.vision.toggle_absent()
        elif action == "clear_alert":
            await app.announcer.clear()
        elif action == "message":
            await self.incoming_message()
        elif action == "gmail_expire":
            inbox = app.messages.sources.get("gmail")
            if isinstance(inbox, MockInbox):
                inbox.expired = True
                await app.messages.refresh("gmail")
            else:  # reconnect
                fresh = MockInbox("gmail", self.now())
                await app.messages.connected("gmail", fresh)
        elif action == "calendar_offline":
            await app.calendar.set_offline(not app.calendar.offline)
        elif action == "focus":
            if app.focus.active:
                await app.focus.stop_focus()
            else:
                await app.focus.start_focus(50)
        elif action == "next_track":
            await app.music.control("next")
        elif action == "toggle_play":
            await app.music.control("pause" if (app.music.current or {}).get("is_playing") else "play")
