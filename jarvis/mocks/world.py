"""Mock world: fake integrations, camera, and voice, driven through the event bus.

Lets the whole app run on any machine without hardware or API keys.
"""

from __future__ import annotations

import asyncio
import math
import random
from datetime import datetime, timedelta
from typing import Any

from jarvis.core.config import Config
from jarvis.core.event_bus import EventBus
from jarvis.core.timeutil import epoch_ms, iso, spoken_time
from jarvis.mocks import data

CORE_STATES = ("idle", "listening", "thinking", "speaking", "alert", "offline")


class MockWorld:
    def __init__(self, config: Config, bus: EventBus) -> None:
        self.config = config
        self.bus = bus
        self.tz = config.tz
        self._tasks: list[asyncio.Task] = []
        self._level_task: asyncio.Task | None = None
        self._convo_task: asyncio.Task | None = None
        self._convo_index = 0
        self._alert_seq = 0

        now = self.now()
        self.schedule = data.schedule(now)
        self.calendar_offline = False
        self.reminders = data.reminders(now)
        self.messages = data.messages(now)
        self.track_index = 0
        self.is_playing = True
        self.progress_ms = 83_000
        self.progress_at = epoch_ms()
        self.volume = 62
        self.focus_week = data.focus_week(now)
        self.focus_session: dict[str, Any] | None = None

    def now(self) -> datetime:
        return datetime.now(self.tz)

    # ---- lifecycle -------------------------------------------------------

    async def start(self) -> None:
        await self.publish_all()
        self._tasks = [
            asyncio.create_task(self._playback_loop(), name="mock-playback"),
            asyncio.create_task(self._inbox_loop(), name="mock-inbox"),
            asyncio.create_task(self._drowsiness_loop(), name="mock-drowsiness"),
        ]

    async def stop(self) -> None:
        for task in [*self._tasks, self._level_task, self._convo_task]:
            if task:
                task.cancel()
        await asyncio.gather(*(t for t in self._tasks if t), return_exceptions=True)

    async def publish_all(self) -> None:
        await self.publish_status()
        await self.set_core("idle")
        await self.publish_schedule()
        await self.publish_reminders()
        await self.publish_messages()
        await self.publish_now_playing()
        await self.publish_focus()
        await self.bus.publish("drowsiness", {"score": 0.08, "enabled": True, "nap_until": None})

    # ---- publishers ------------------------------------------------------

    async def publish_status(self) -> None:
        gmail_auth = self.messages["gmail"]["auth"]
        await self.bus.publish(
            "status",
            {
                "mock": True,
                "dev": True,
                "user_name": self.config.user_name,
                "camera": "mock",
                "mic": "mock",
                "integrations": {
                    "calendar": "offline" if self.calendar_offline else "ok",
                    "gmail": gmail_auth,
                    "slack": self.messages["slack"]["auth"],
                    "spotify": "ok",
                    "claude": "mock",
                },
                "llm": {"calls": 14, "tokens": 23_400, "limit": self.config.llm.daily_token_limit},
            },
        )

    async def set_core(self, core: str) -> None:
        await self.bus.publish("state", {"core": core})
        if self._level_task:
            self._level_task.cancel()
            self._level_task = None
        if core in ("listening", "speaking"):
            self._level_task = asyncio.create_task(self._level_loop(core))

    async def publish_schedule(self) -> None:
        await self.bus.publish(
            "schedule",
            {"events": self.schedule, "synced_at": iso(self.now()), "offline": self.calendar_offline},
        )

    async def publish_reminders(self) -> None:
        items = sorted(self.reminders, key=lambda r: r["when"])
        await self.bus.publish("reminders", {"items": items})

    async def publish_messages(self) -> None:
        payload = {}
        for source, box in self.messages.items():
            items = sorted(box["items"], key=lambda m: m["received_at"], reverse=True)
            payload[source] = {"auth": box["auth"], "count": len(items), "items": items[:5]}
        await self.bus.publish("messages", payload)

    async def publish_now_playing(self) -> None:
        track = data.TRACKS[self.track_index]
        await self.bus.publish(
            "now_playing",
            {
                "title": track["title"],
                "artist": track["artist"],
                "album": track["album"],
                "art_url": None,
                "art_hue": track["hue"],
                "duration_ms": track["duration_ms"],
                "progress_ms": self._progress(),
                "updated_at": epoch_ms(),
                "is_playing": self.is_playing,
                "volume": self.volume,
            },
        )

    async def publish_focus(self) -> None:
        await self.bus.publish(
            "focus",
            {"today_min": self.focus_week[-1]["min"], "week": self.focus_week, "session": self.focus_session},
        )

    def _progress(self) -> int:
        if not self.is_playing:
            return self.progress_ms
        return self.progress_ms + (epoch_ms() - self.progress_at)

    # ---- background loops --------------------------------------------------

    async def _playback_loop(self) -> None:
        while True:
            await asyncio.sleep(1)
            track = data.TRACKS[self.track_index]
            if self.is_playing and self._progress() >= track["duration_ms"]:
                await self.skip(1)
            if self.focus_session and not self.focus_session["paused"]:
                if epoch_ms() >= self.focus_session["ends_at"]:
                    await self._finish_focus()

    async def _inbox_loop(self) -> None:
        while True:
            await asyncio.sleep(random.uniform(240, 420))
            await self.incoming_message()

    async def _drowsiness_loop(self) -> None:
        t = 0.0
        while True:
            await asyncio.sleep(2)
            t += 2
            score = 0.1 + 0.06 * math.sin(t / 17) + random.uniform(-0.03, 0.03)
            await self.bus.publish("drowsiness", {"score": round(max(0.0, score), 3), "enabled": True, "nap_until": None})

    async def _level_loop(self, mode: str) -> None:
        t = 0.0
        try:
            while True:
                t += 0.05
                if mode == "listening":
                    # Bursty "speech" with pauses.
                    env = max(0.0, math.sin(t * 2.3)) * (0.5 + 0.5 * math.sin(t * 0.7))
                    v = 0.08 + env * random.uniform(0.5, 1.0)
                else:
                    # Syllable-rate envelope.
                    v = 0.2 + 0.6 * abs(math.sin(t * 6.5)) * random.uniform(0.6, 1.0)
                await self.bus.publish("level", {"v": round(min(v, 1.0), 3)})
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            await self.bus.publish("level", {"v": 0})
            raise

    # ---- actions -------------------------------------------------------------

    async def skip(self, direction: int) -> None:
        self.track_index = (self.track_index + direction) % len(data.TRACKS)
        self.progress_ms = 0
        self.progress_at = epoch_ms()
        await self.publish_now_playing()

    async def toggle_play(self) -> None:
        self.progress_ms = self._progress()
        self.progress_at = epoch_ms()
        self.is_playing = not self.is_playing
        await self.publish_now_playing()

    async def incoming_message(self) -> None:
        source, sender, subject, snippet = next(data.INCOMING)
        box = self.messages[source]
        box["items"].append(
            {
                "id": f"{source}-{epoch_ms()}",
                "sender": sender,
                "subject": subject,
                "snippet": snippet,
                "received_at": iso(self.now()),
            }
        )
        await self.publish_messages()

    async def alert(self, kind: str, level: int, title: str, body: str = "") -> None:
        self._alert_seq += 1
        await self.bus.publish(
            "alert",
            {"id": self._alert_seq, "kind": kind, "level": level, "title": title, "body": body, "active": True},
        )
        await self.set_core("alert")

    async def clear_alert(self) -> None:
        await self.bus.publish("alert", {"id": self._alert_seq, "active": False})
        await self.set_core("idle")

    async def toggle_focus(self) -> None:
        if self.focus_session:
            await self._finish_focus()
            return
        planned = 50
        self.focus_session = {
            "planned_min": planned,
            "started_at": epoch_ms(),
            "ends_at": epoch_ms() + planned * 60_000,
            "paused": False,
        }
        await self.publish_focus()

    async def _finish_focus(self) -> None:
        session = self.focus_session
        self.focus_session = None
        if session:
            done_min = max(0, (epoch_ms() - session["started_at"]) // 60_000)
            self.focus_week[-1]["min"] += int(done_min)
        await self.publish_focus()

    async def converse(self) -> None:
        if self._convo_task and not self._convo_task.done():
            return
        self._convo_task = asyncio.create_task(self._run_conversation())

    async def _run_conversation(self) -> None:
        script = [self._c_time, self._c_reminder, self._c_schedule, self._c_music]
        turn = script[self._convo_index % len(script)]
        self._convo_index += 1
        question, make_reply = turn()

        await self.set_core("listening")
        words = question.split(" ")
        for i in range(1, len(words) + 1):
            await asyncio.sleep(0.35)
            await self.bus.publish("transcript", {"role": "user", "text": " ".join(words[:i]), "final": False})
        await asyncio.sleep(0.5)
        await self.bus.publish("transcript", {"role": "user", "text": question, "final": True})

        await self.set_core("thinking")
        await asyncio.sleep(1.4)
        reply = await make_reply()

        await self.set_core("speaking")
        await self.bus.publish("transcript", {"role": "jarvis", "text": reply, "final": True})
        await asyncio.sleep(min(6.0, 1.2 + len(reply) * 0.07))
        await self.set_core("idle")

    def _c_time(self):
        async def reply() -> str:
            return f"지금은 {spoken_time(self.now())}이에요."

        return "지금 몇 시야?", reply

    def _c_reminder(self):
        async def reply() -> str:
            when = (self.now() + timedelta(minutes=30)).replace(second=0, microsecond=0)
            new_id = max((r["id"] for r in self.reminders), default=0) + 1
            self.reminders.append({"id": new_id, "message": "빨래 널기", "when": iso(when), "repeat": None})
            await self.publish_reminders()
            return f"{spoken_time(when)}에 빨래 널라고 알려드릴게요."

        return "30분 뒤에 빨래 널라고 알려줘", reply

    def _c_schedule(self):
        async def reply() -> str:
            now = self.now()
            upcoming = [e for e in self.schedule if datetime.fromisoformat(e["start"]) > now]
            if not upcoming:
                return "오늘 남은 일정은 없어요."
            first = upcoming[0]
            start = datetime.fromisoformat(first["start"])
            rest = f" 그 뒤로 {len(upcoming) - 1}개가 더 있어요." if len(upcoming) > 1 else ""
            return f"{spoken_time(start)}에 {first['title']}이 있어요.{rest}"

        return "오늘 남은 일정 뭐야?", reply

    def _c_music(self):
        async def reply() -> str:
            self.track_index = 1
            self.progress_ms = 0
            self.progress_at = epoch_ms()
            self.is_playing = True
            await self.publish_now_playing()
            return "잔잔한 재즈로 틀어드릴게요."

        return "잔잔한 재즈 틀어줘", reply

    # ---- dev controls ---------------------------------------------------------

    async def handle_dev(self, action: str, value: Any = None) -> None:
        if action == "state" and value in CORE_STATES:
            await self.set_core(value)
        elif action == "converse":
            await self.converse()
        elif action == "reminder":
            item = self.reminders[0] if self.reminders else {"message": "빨래 꺼내기"}
            await self.alert("reminder", 1, f"지금은 {item['message']} 할 차례예요.")
        elif action == "event":
            await self.alert("event", 1, "10분 뒤 UMC 스터디", "준비물: 발표 자료")
        elif action == "drowsy":
            level = 2 if value == 2 else 1
            title = "재원님, 졸고 계신 것 같아요." if level == 1 else "재원님! 일어나세요!"
            await self.alert("drowsy", level, title)
        elif action == "clear_alert":
            await self.clear_alert()
        elif action == "message":
            await self.incoming_message()
        elif action == "gmail_expire":
            box = self.messages["gmail"]
            box["auth"] = "expired" if box["auth"] == "ok" else "ok"
            await self.publish_messages()
            await self.publish_status()
        elif action == "calendar_offline":
            self.calendar_offline = not self.calendar_offline
            await self.publish_schedule()
            await self.publish_status()
        elif action == "focus":
            await self.toggle_focus()
        elif action == "next_track":
            await self.skip(1)
        elif action == "toggle_play":
            await self.toggle_play()

    async def handle_ptt(self, down: bool) -> None:
        if down:
            await self.converse()

    async def handle_alert_ack(self) -> None:
        await self.clear_alert()
