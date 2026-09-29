"""Calendar (F5): today's timeline, pre-/start alerts, and local schedule questions.

Events come from Google Calendar (the calendars Notion Calendar shows) every 5 minutes,
are cached in SQLite for offline use, or — in mock mode — from the mock world.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx2

from jarvis.brain.context import Context
from jarvis.brain.tools import Tool, ToolRegistry, schema
from jarvis.core.announcer import Announcer
from jarvis.core.db import Database
from jarvis.core.event_bus import EventBus
from jarvis.core.presence import Presence
from jarvis.core.settings import Settings
from jarvis.core.status import StatusBoard
from jarvis.core.timeutil import WEEKDAYS_KO, spoken_time
from jarvis.integrations.oauth import AuthRequired

log = logging.getLogger(__name__)

SYNC_EVERY_SEC = 5 * 60
ALERT_CHECK_SEC = 15
START_GRACE = timedelta(minutes=2)  # still announce a start this late (e.g. after a restart)
WEEKDAY_CHARS = "월화수목금토일"
PERIOD_HOURS = {
    "오전": (0, 12), "아침": (5, 11), "점심": (11, 14), "오후": (12, 24), "저녁": (17, 23), "밤": (18, 24),
}
ASK = r"(일정|스케줄|약속)?(은|이|좀)?(뭐|뭐야|뭐있어|뭐있지|뭐있나|있어|있나|알려줘|어때|확인해줘|말해줘)+(요)?"


def _day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


class CalendarService:
    def __init__(
        self,
        db: Database,
        bus: EventBus,
        status: StatusBoard,
        announcer: Announcer,
        presence: Presence,
        settings: Settings,
        clock: Callable[[], datetime],
        source: Any = None,  # GoogleCalendarSource, or None (mock / not configured)
        configured: bool = False,
    ) -> None:
        self.db = db
        self.bus = bus
        self.status = status
        self.announcer = announcer
        self.presence = presence
        self.settings = settings
        self.clock = clock
        self.source = source
        self.configured = configured
        self.events: list[dict[str, Any]] = []
        self.offline = False
        self.synced_at: datetime | None = None
        self._announced: set[str] = set()
        self._tasks: list[asyncio.Task] = []
        self._first_check = True

    # ---- data -----------------------------------------------------------------------

    def _load_cache(self) -> None:
        tz = self.clock().tzinfo
        rows = self.db.conn.execute(
            "SELECT id, calendar_id, title, start_utc, end_utc, all_day FROM events_cache ORDER BY start_utc"
        ).fetchall()
        self.events = [
            {
                "id": r["id"],
                "title": r["title"],
                "start": datetime.fromisoformat(r["start_utc"]).astimezone(tz),
                "end": datetime.fromisoformat(r["end_utc"]).astimezone(tz),
                "all_day": bool(r["all_day"]),
                "calendar": r["calendar_id"],
            }
            for r in rows
        ]

    def _save_cache(self) -> None:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.db.conn:
            self.db.conn.execute("DELETE FROM events_cache")
            self.db.conn.executemany(
                "INSERT OR REPLACE INTO events_cache (id, calendar_id, title, start_utc, end_utc, updated_at, all_day)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        e["id"], e["calendar"], e["title"],
                        e["start"].astimezone(timezone.utc).isoformat(), e["end"].astimezone(timezone.utc).isoformat(),
                        stamp, int(e["all_day"]),
                    )
                    for e in self.events
                ],
            )

    async def set_events(self, events: list[dict[str, Any]]) -> None:
        """Mock mode: events with ISO strings or datetimes."""
        tz = self.clock().tzinfo
        norm = []
        for e in events:
            start = e["start"] if isinstance(e["start"], datetime) else datetime.fromisoformat(e["start"])
            end = e["end"] if isinstance(e["end"], datetime) else datetime.fromisoformat(e["end"])
            norm.append({**e, "start": start.astimezone(tz), "end": end.astimezone(tz), "all_day": e.get("all_day", False)})
        self.events = sorted(norm, key=lambda ev: ev["start"])
        self.synced_at = self.clock()
        await self.publish()

    async def set_offline(self, offline: bool) -> None:
        self.offline = offline
        await self.status.update(integrations={"calendar": "offline" if offline else "ok"})
        await self.publish()

    def between(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        return [e for e in self.events if e["start"] < end and e["end"] > start]

    def upcoming(self, now: datetime) -> list[dict[str, Any]]:
        return [e for e in self.events if e["start"] > now and not e["all_day"]]

    async def publish(self) -> None:
        now = self.clock()
        today = self.between(_day_start(now), _day_start(now) + timedelta(days=1))
        await self.bus.publish(
            "schedule",
            {
                "events": [
                    {
                        "id": e["id"],
                        "title": e["title"],
                        "start": e["start"].isoformat(timespec="seconds"),
                        "end": e["end"].isoformat(timespec="seconds"),
                        "all_day": e["all_day"],
                        "calendar": e["calendar"],
                    }
                    for e in today
                ],
                "synced_at": self.synced_at.isoformat(timespec="seconds") if self.synced_at else None,
                "offline": self.offline,
            },
        )

    # ---- lifecycle ---------------------------------------------------------------------

    async def start(self, mock: bool = False) -> None:
        if not mock:
            self._load_cache()
            state = "disabled" if not self.configured else "expired" if self.source is None else "ok"
            await self.status.update(integrations={"calendar": state})
            await self.publish()
            if self.source is not None:
                self._tasks.append(asyncio.create_task(self._sync_loop(), name="calendar-sync"))
        self._tasks.append(asyncio.create_task(self._alert_loop(), name="calendar-alerts"))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()

    async def connected(self, source: Any) -> None:
        """Called after the user finishes OAuth."""
        self.source = source
        self.configured = True
        if not any(t.get_name() == "calendar-sync" for t in self._tasks if not t.done()):
            self._tasks.append(asyncio.create_task(self._sync_loop(), name="calendar-sync"))

    async def sync(self) -> bool:
        if self.source is None:
            return False
        now = self.clock()
        try:
            self.events = await self.source.fetch(_day_start(now))
        except AuthRequired:
            log.warning("calendar needs re-authorisation")
            self.source = None
            await self.status.update(integrations={"calendar": "expired"})
            await self.publish()
            return False
        except (httpx2.HTTPError, OSError) as e:
            log.warning("calendar sync failed (%s); showing cached events", type(e).__name__)
            self.offline = True
            await self.status.update(integrations={"calendar": "offline"})
            await self.publish()
            return False
        self._save_cache()
        self.offline = False
        self.synced_at = now
        await self.status.update(integrations={"calendar": "ok"})
        await self.publish()
        return True

    async def _sync_loop(self) -> None:
        while self.source is not None:
            await self.sync()
            await asyncio.sleep(SYNC_EVERY_SEC)

    async def _alert_loop(self) -> None:
        last_day = self.clock().date()
        while True:
            try:
                await self.check_alerts()
                if self.clock().date() != last_day:  # midnight: roll the timeline over
                    last_day = self.clock().date()
                    await self.publish()
            except Exception:
                log.exception("calendar alert check failed")
            await asyncio.sleep(ALERT_CHECK_SEC)

    async def check_alerts(self) -> int:
        now = self.clock()
        pre = timedelta(minutes=int(self.settings["pre_alert_min"]))
        fired = 0
        for e in self.events:
            if e["all_day"] or e["start"] > now + pre + timedelta(seconds=1) or e["start"] < now - START_GRACE:
                continue
            key = f"{e['id']}@{e['start'].isoformat()}"
            if e["start"] <= now:
                if f"start:{key}" not in self._announced:
                    self._announced.add(f"start:{key}")
                    self._announced.add(f"pre:{key}")
                    if self.settings["event_start_alert"] and not self._first_check:
                        text = f"지금은 {e['title']} 시간이에요."
                        await self.announcer.notify("event", text, say=text)
                        fired += 1
            elif f"pre:{key}" not in self._announced:
                self._announced.add(f"pre:{key}")
                if self.settings["event_pre_alert"]:
                    mins = max(1, round((e["start"] - now).total_seconds() / 60))
                    text = f"{mins}분 뒤에 {e['title']} 일정이 있어요."
                    await self.announcer.notify("event", text, body=f"{spoken_time(e['start'])} 시작", say=text)
                    fired += 1
        # Events already running at startup are not announced as "starting now".
        self._first_check = False
        return fired

    # ---- local questions --------------------------------------------------------------------

    def _describe(self, events: list[dict[str, Any]], now: datetime, limit: int = 4) -> str:
        private = not self.presence.owner_here
        parts = []
        for e in events[:limit]:
            if e["all_day"]:
                parts.append("종일 일정" if private else f"종일 {e['title']}")
            else:
                parts.append(spoken_time(e["start"]) + ("" if private else f" {e['title']}"))
        more = f" 외에 {len(events) - limit}개가 더 있어요." if len(events) > limit else ""
        return ", ".join(parts) + "." + more

    def _prefix(self) -> str:
        return "연결이 끊겨서 저장된 일정 기준이에요. " if self.offline else ""

    async def handle(self, text: str, key: str, ctx: Context) -> str | None:
        now = ctx.now
        if not self.events and self.source is None and not self.configured and not self.synced_at:
            if re.search(r"(일정|스케줄|약속)", key):
                return "캘린더가 아직 연결되지 않았어요. 설정 안내의 Google 캘린더 연결을 먼저 해 주세요."
            return None

        if re.fullmatch(rf"다음(일정|스케줄|약속)(이|은)?(뭐|뭐야|언제|언제야|알려줘|있어)*(요)?", key):
            nxt = self.upcoming(now)
            if not nxt:
                return self._prefix() + "오늘 남은 일정은 없어요."
            e = nxt[0]
            mins = round((e["start"] - now).total_seconds() / 60)
            title = "" if not self.presence.owner_here else f" {e['title']}"
            return self._prefix() + f"다음 일정은 {spoken_time(e['start'])}{title}이고, {mins}분 남았어요."

        m = re.fullmatch(rf"(오늘|내일|모레)(남은)?({'|'.join(PERIOD_HOURS)})?(에)?(남은)?{ASK}", key)
        if m or re.fullmatch(r"오늘(남은)?(일정|스케줄)", key):
            day_word = m.group(1) if m else "오늘"
            period = m.group(3) if m else None
            offset = {"오늘": 0, "내일": 1, "모레": 2}[day_word]
            start = _day_start(now) + timedelta(days=offset)
            end = start + timedelta(days=1)
            if period:
                h0, h1 = PERIOD_HOURS[period]
                start, end = start + timedelta(hours=h0), start + timedelta(hours=h1)
            events = self.between(start, end)
            if offset == 0:
                events = [e for e in events if e["all_day"] or e["end"] > now]
            label = f"{day_word}{' ' + period if period else ''}"
            if not events:
                return self._prefix() + f"{label}{'은' if not period else '에는'} {'남은 ' if offset == 0 and not period else ''}일정이 없어요."
            return self._prefix() + f"{label} 일정은 {len(events)}개예요. " + self._describe(events, now)

        w = re.fullmatch(
            rf"(이번주|다음주|담주)?([{WEEKDAY_CHARS}])요일(에|은|엔)?(오전|오후|저녁)?(에)?"
            r"(비어|비었|한가|시간|일정|약속|뭐|스케줄)(있어|있나|있어요|해|해요|돼|되나|되니|이야|있지|있니|뭐야|어때)?(\?)?",
            key,
        )
        if w:
            target = WEEKDAY_CHARS.index(w.group(2))
            offset = (target - now.weekday()) % 7
            if w.group(1) in ("다음주", "담주"):
                offset += 7 if offset else 7
            start = _day_start(now) + timedelta(days=offset)
            end = start + timedelta(days=1)
            if w.group(4):
                h0, h1 = PERIOD_HOURS[w.group(4)]
                start, end = start + timedelta(hours=h0), start + timedelta(hours=h1)
            events = self.between(start, end)
            label = f"{start.month}월 {start.day}일 {WEEKDAYS_KO[start.weekday()]}요일"
            if offset >= 8:
                return None  # beyond the synced window: let the LLM say it does not know
            if not events:
                return self._prefix() + f"{label}{' ' + w.group(4) if w.group(4) else ''}은 비어 있어요."
            return self._prefix() + f"{label}에는 일정이 {len(events)}개 있어요. " + self._describe(events, now)
        return None

    def register_tools(self, tools: ToolRegistry) -> None:
        """Only registered when personal data may reach the LLM."""

        async def get_schedule(args: dict[str, Any]) -> dict[str, Any]:
            tz = self.clock().tzinfo
            start = datetime.fromisoformat(args["start_iso"])
            end = datetime.fromisoformat(args["end_iso"])
            start = start if start.tzinfo else start.replace(tzinfo=tz)
            end = end if end.tzinfo else end.replace(tzinfo=tz)
            return {
                "offline": self.offline,
                "events": [
                    {"title": e["title"], "start": e["start"].isoformat(), "end": e["end"].isoformat(), "all_day": e["all_day"]}
                    for e in self.between(start, end)
                ],
            }

        tools.register(
            Tool(
                "get_schedule",
                "캐시된 캘린더 일정을 조회한다 (앞으로 약 7일). 시각은 KST ISO 8601.",
                schema({"start_iso": {"type": "string"}, "end_iso": {"type": "string"}}, ["start_iso", "end_iso"]),
                get_schedule,
            )
        )
