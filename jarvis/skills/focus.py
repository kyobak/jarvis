"""Focus mode (F8, pomodoro-style, paused while away) and nap mode (F2: no drowsiness
alerts for N minutes, then a wake-up call)."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from jarvis.brain.context import Context
from jarvis.brain.timeparse import NUM, to_int
from jarvis.brain.tools import Tool, ToolRegistry, schema
from jarvis.core.announcer import Announcer
from jarvis.core.db import Database
from jarvis.core.event_bus import EventBus
from jarvis.core.timeutil import spoken_time

log = logging.getLogger(__name__)

DEFAULT_FOCUS_MIN = 50
DEFAULT_NAP_MIN = 30


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def hours_words(minutes: int) -> str:
    h, m = divmod(max(0, int(minutes)), 60)
    if h and m:
        return f"{h}시간 {m}분"
    return f"{h}시간" if h else f"{m}분"


class FocusService:
    def __init__(self, db: Database, bus: EventBus, announcer: Announcer, clock: Callable[[], datetime]) -> None:
        self.db = db
        self.bus = bus
        self.announcer = announcer
        self.clock = clock
        self.session: dict[str, Any] | None = None  # id, planned_min, started, ends, paused_at, paused_sec
        self.nap_until: datetime | None = None
        self._task: asyncio.Task | None = None
        self._nap_task: asyncio.Task | None = None
        self.on_nap_end: list[Callable[[], Any]] = []

    # ---- focus -------------------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self.session is not None

    def remaining(self) -> timedelta:
        s = self.session
        if not s:
            return timedelta()
        end = s["ends"] + timedelta(seconds=s["paused_sec"])
        now = s["paused_at"] or self.clock()
        return max(timedelta(), end - now)

    async def start_focus(self, minutes: int = DEFAULT_FOCUS_MIN) -> dict[str, Any]:
        if self.session:
            await self.stop_focus(completed=False)
        minutes = max(1, min(int(minutes), 240))
        now = self.clock()
        with self.db.conn:
            cur = self.db.conn.execute(
                "INSERT INTO focus_sessions (start_utc, planned_min) VALUES (?, ?)",
                (now.astimezone(timezone.utc).isoformat(timespec="seconds"), minutes),
            )
        self.session = {"id": cur.lastrowid, "planned_min": minutes, "started": now,
                        "ends": now + timedelta(minutes=minutes), "paused_at": None, "paused_sec": 0}
        self._task = asyncio.create_task(self._watch(), name="focus-timer")
        await self.publish()
        return {"planned_min": minutes, "ends": (now + timedelta(minutes=minutes)).isoformat(timespec="minutes")}

    async def stop_focus(self, completed: bool = False) -> int:
        """Ends the session; returns the minutes actually focused."""
        s = self.session
        if not s:
            return 0
        if self._task and self._task is not asyncio.current_task():
            self._task.cancel()
        now = self.clock()
        paused = s["paused_sec"] + ((now - s["paused_at"]).total_seconds() if s["paused_at"] else 0)
        actual = max(0, int(((now - s["started"]).total_seconds() - paused) // 60))
        if completed:
            actual = s["planned_min"]
        with self.db.conn:
            self.db.conn.execute(
                "UPDATE focus_sessions SET end_utc = ?, actual_min = ?, paused_sec = ? WHERE id = ?",
                (now.astimezone(timezone.utc).isoformat(timespec="seconds"), actual, int(paused), s["id"]),
            )
        self.session = None
        await self.publish()
        return actual

    async def pause(self) -> None:
        if self.session and not self.session["paused_at"]:
            self.session["paused_at"] = self.clock()
            await self.publish()

    async def resume(self) -> None:
        s = self.session
        if s and s["paused_at"]:
            s["paused_sec"] += int((self.clock() - s["paused_at"]).total_seconds())
            s["paused_at"] = None
            await self.publish()

    async def _watch(self) -> None:
        while self.session:
            if not self.session["paused_at"] and self.remaining() <= timedelta():
                planned = self.session["planned_min"]
                await self.stop_focus(completed=True)
                text = f"집중 {planned}분이 끝났어요. 잠깐 쉬었다 해요."
                await self.announcer.notify("focus", text, say=text, personal=False)
                return
            await asyncio.sleep(1)

    def minutes_on(self, day: datetime) -> int:
        start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        rows = self.db.conn.execute(
            "SELECT start_utc, actual_min FROM focus_sessions WHERE actual_min IS NOT NULL AND start_utc >= ? AND start_utc < ?",
            (start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()),
        ).fetchall()
        total = sum(r["actual_min"] or 0 for r in rows)
        s = self.session
        if s and start <= s["started"] < end:
            now = s["paused_at"] or self.clock()
            total += max(0, int(((now - s["started"]).total_seconds() - s["paused_sec"]) // 60))
        return total

    def week(self) -> list[dict[str, Any]]:
        now = self.clock()
        return [
            {"date": (now - timedelta(days=b)).date().isoformat(), "min": self.minutes_on(now - timedelta(days=b))}
            for b in range(6, -1, -1)
        ]

    async def publish(self) -> None:
        s = self.session
        session = None
        if s:
            session = {
                "planned_min": s["planned_min"],
                "started_at": _ms(s["started"]),
                "ends_at": _ms(self.clock() + self.remaining()),
                "paused": bool(s["paused_at"]),
                "remaining_ms": int(self.remaining().total_seconds() * 1000),
            }
        week = self.week()
        await self.bus.publish("focus", {"today_min": week[-1]["min"], "week": week, "session": session})

    # ---- nap ---------------------------------------------------------------------------

    @property
    def napping(self) -> bool:
        return self.nap_until is not None and self.clock() < self.nap_until

    async def start_nap(self, minutes: int = DEFAULT_NAP_MIN) -> datetime:
        minutes = max(1, min(int(minutes), 180))
        self.nap_until = self.clock() + timedelta(minutes=minutes)
        if self._nap_task:
            self._nap_task.cancel()
        self._nap_task = asyncio.create_task(self._nap_alarm(), name="nap-alarm")
        await self.bus.publish("nap", {"until": self.nap_until.isoformat(timespec="seconds")})
        return self.nap_until

    async def cancel_nap(self) -> bool:
        if not self.nap_until:
            return False
        self.nap_until = None
        if self._nap_task and self._nap_task is not asyncio.current_task():
            self._nap_task.cancel()
        await self.bus.publish("nap", {"until": None})
        return True

    async def _nap_alarm(self) -> None:
        while self.nap_until and self.clock() < self.nap_until:
            await asyncio.sleep(min(5.0, max(0.05, (self.nap_until - self.clock()).total_seconds())))
        if self.nap_until is None:
            return
        self.nap_until = None
        await self.bus.publish("nap", {"until": None})
        text = "낮잠 시간이 끝났어요. 일어나실 시간이에요."
        await self.announcer.notify("drowsy", text, say=text, level=2, personal=False, sound="Sosumi", force_voice=True)
        for hook in self.on_nap_end:
            result = hook()
            if asyncio.iscoroutine(result):
                await result

    # ---- voice + tools --------------------------------------------------------------------

    async def handle(self, text: str, key: str, ctx: Context) -> str | None:
        m = re.search(rf"{NUM}\s*(시간|분)", text)
        amount = None
        if m:
            amount = to_int(m.group(1)) * (60 if m.group(2) == "시간" else 1)
            if "반" in text[m.end() : m.end() + 2]:
                amount += 30 if m.group(2) == "시간" else 0
        if re.search(r"(집중|공부|포모도로)(모드|타이머)?(를|을)?(끝|종료|그만|멈춰|중지|취소)", key):
            if not self.session:
                return "진행 중인 집중 모드가 없어요."
            done = await self.stop_focus()
            return f"집중 모드를 끝냈어요. 이번에 {hours_words(done)} 집중했어요."
        if re.search(r"(집중|공부|포모도로)(모드|타이머)?(를|을)?.*(시작|켜|해줘|할게|하자)", key):
            minutes = amount or DEFAULT_FOCUS_MIN
            await self.start_focus(minutes)
            end = ctx.now + timedelta(minutes=minutes)
            return f"{hours_words(minutes)} 집중 모드를 시작할게요. {spoken_time(end)}에 알려드릴게요."
        if re.search(r"(오늘|이번주)?.*(얼마나|몇시간|몇분).*(공부|집중)|(공부|집중)(시간|한시간).*(얼마|몇)", key):
            if "이번주" in key or "일주일" in key:
                total = sum(d["min"] for d in self.week())
                return f"이번 주에는 {hours_words(total)} 집중했어요."
            return f"오늘은 {hours_words(self.minutes_on(ctx.now))} 집중했어요."
        if re.search(r"(낮잠|잠깐|쪽잠).*(잘게|잘래|자고|모드|잘거야)|(분|시간)만잘게|낮잠모드", key):
            minutes = amount or DEFAULT_NAP_MIN
            until = await self.start_nap(minutes)
            return f"{hours_words(minutes)} 동안 졸음 감지를 끌게요. {spoken_time(until)}에 깨워 드릴게요. 잘 자요."
        if re.search(r"(낮잠|잠)(에서)?(깼어|일어났어|끝|그만|취소)", key):
            return "낮잠 모드를 끝냈어요." if await self.cancel_nap() else None
        return None

    def register_tools(self, tools: ToolRegistry) -> None:
        async def start_focus(args: dict[str, Any]) -> dict[str, Any]:
            return await self.start_focus(int(args.get("minutes") or DEFAULT_FOCUS_MIN))

        async def stop_focus(_: dict[str, Any]) -> dict[str, Any]:
            return {"focused_min": await self.stop_focus()}

        async def get_focus_stats(args: dict[str, Any]) -> dict[str, Any]:
            if args.get("range") == "week":
                return {"days": self.week()}
            return {"today_min": self.minutes_on(self.clock())}

        async def set_nap(args: dict[str, Any]) -> dict[str, Any]:
            until = await self.start_nap(int(args.get("minutes") or DEFAULT_NAP_MIN))
            return {"wake_at": until.isoformat(timespec="minutes")}

        tools.register(Tool("start_focus", "집중 모드(포모도로)를 시작한다.",
                            schema({"minutes": {"type": "integer"}}, ["minutes"]), start_focus))
        tools.register(Tool("stop_focus", "집중 모드를 끝낸다.", schema(), stop_focus))
        tools.register(Tool("get_focus_stats", "집중(공부) 시간 통계. range는 today 또는 week.",
                            schema({"range": {"type": "string", "enum": ["today", "week"]}}, ["range"]), get_focus_stats))
        tools.register(Tool("set_nap", "낮잠 모드: 주어진 분 동안 졸음 감지를 끄고 끝나면 깨운다.",
                            schema({"minutes": {"type": "integer"}}, ["minutes"]), set_nap))
