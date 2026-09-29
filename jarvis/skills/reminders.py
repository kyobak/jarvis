"""Reminders (F4): stored in SQLite so they survive restarts; fired within about a second.

A single task sleeps until the earliest pending reminder (or until something changes).
Repeating reminders are rescheduled after firing.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from jarvis.brain.context import Context
from jarvis.brain.router import squash
from jarvis.brain.timeparse import next_occurrence, parse_reminder, repeat_label
from jarvis.brain.tools import Tool, ToolRegistry, schema
from jarvis.core.announcer import Announcer
from jarvis.core.db import Database
from jarvis.core.event_bus import EventBus
from jarvis.core.timeutil import spoken_time

log = logging.getLogger(__name__)

MAX_WAIT_SEC = 30.0  # re-check at least this often (clock changes, sleep/wake)
LATE_LIMIT = timedelta(minutes=10)  # older than this at startup counts as missed
REPEAT_RULE = re.compile(r"^(daily|weekdays|weekends|weekly:[0-6](,[0-6])*)$")


def spoken_when(when: datetime, now: datetime) -> str:
    days = (when.date() - now.date()).days
    prefix = "" if days == 0 else "내일 " if days == 1 else "모레 " if days == 2 else f"{when.month}월 {when.day}일 "
    return prefix + spoken_time(when)


def due_sentence(message: str) -> str:
    if message == "알림":
        return "요청하신 알림 시간이에요."
    if message == "일어나기":
        return "일어나실 시간이에요."
    return f"지금은 {message} 할 차례예요."


class ReminderService:
    def __init__(self, db: Database, bus: EventBus, announcer: Announcer, clock: Callable[[], datetime]) -> None:
        self.db = db
        self.bus = bus
        self.announcer = announcer
        self.clock = clock
        self._changed = asyncio.Event()
        self._task: asyncio.Task | None = None

    # ---- storage ----------------------------------------------------------------

    def _rows(self, status: str = "pending") -> list[dict[str, Any]]:
        rows = self.db.conn.execute(
            "SELECT id, message, when_utc, repeat_rule FROM reminders WHERE status = ? ORDER BY when_utc", (status,)
        ).fetchall()
        return [dict(r) for r in rows]

    def _local(self, when_utc: str) -> datetime:
        return datetime.fromisoformat(when_utc).astimezone(self.clock().tzinfo)

    def pending(self) -> list[dict[str, Any]]:
        return [
            {
                "id": r["id"],
                "message": r["message"],
                "when": self._local(r["when_utc"]).isoformat(timespec="seconds"),
                "repeat": repeat_label(r["repeat_rule"]),
                "rule": r["repeat_rule"],
            }
            for r in self._rows()
        ]

    async def create(self, when: datetime, message: str, repeat: str | None = None) -> dict[str, Any]:
        if repeat and not REPEAT_RULE.match(repeat):
            raise ValueError(f"bad repeat rule {repeat!r}")
        message = message.strip()[:100] or "알림"
        when_utc = when.astimezone(timezone.utc).isoformat(timespec="seconds")
        with self.db.conn:
            cur = self.db.conn.execute(
                "INSERT INTO reminders (message, when_utc, repeat_rule, status) VALUES (?, ?, ?, 'pending')",
                (message, when_utc, repeat),
            )
        log.info("reminder %d at %s (%s)", cur.lastrowid, when.isoformat(), repeat or "once")
        await self._after_change()
        return {"id": cur.lastrowid, "message": message, "when": when.isoformat(timespec="seconds"), "repeat": repeat}

    async def cancel(self, reminder_id: int) -> bool:
        with self.db.conn:
            cur = self.db.conn.execute(
                "UPDATE reminders SET status = 'cancelled' WHERE id = ? AND status = 'pending'", (reminder_id,)
            )
        if cur.rowcount:
            await self._after_change()
        return bool(cur.rowcount)

    def find(self, words: str) -> list[dict[str, Any]]:
        """Pending reminders whose message shares the given words (squashed substring match)."""
        key = squash(words)
        if not key:
            return []
        return [r for r in self.pending() if key in squash(r["message"]) or squash(r["message"]) in key]

    async def _after_change(self) -> None:
        await self.publish()
        self._changed.set()

    async def publish(self) -> None:
        items = [{k: v for k, v in r.items() if k != "rule"} for r in self.pending()]
        await self.bus.publish("reminders", {"items": items})

    # ---- scheduling ---------------------------------------------------------------

    async def start(self) -> None:
        await self._handle_missed_at_startup()
        await self.publish()
        self._task = asyncio.create_task(self._loop(), name="reminders")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _handle_missed_at_startup(self) -> None:
        now = self.clock()
        missed = []
        for r in self._rows():
            when = self._local(r["when_utc"])
            if now - when > LATE_LIMIT:
                missed.append(r["message"])
                self._advance(r, now, status_if_once="missed")
        if missed:
            log.info("%d reminders were missed while Jarvis was off", len(missed))
            self.announcer.missed.extend(missed)

    def _advance(self, row: dict[str, Any], now: datetime, status_if_once: str = "done") -> None:
        rule = row["repeat_rule"]
        with self.db.conn:
            if rule:
                clock_time = self._local(row["when_utc"]).timetz().replace(tzinfo=None)
                nxt = next_occurrence(rule, clock_time, now)
                self.db.conn.execute(
                    "UPDATE reminders SET when_utc = ? WHERE id = ?",
                    (nxt.astimezone(timezone.utc).isoformat(timespec="seconds"), row["id"]),
                )
            else:
                self.db.conn.execute("UPDATE reminders SET status = ? WHERE id = ?", (status_if_once, row["id"]))

    async def _loop(self) -> None:
        while True:
            try:
                await self.fire_due()
            except Exception:
                log.exception("reminder check failed")
            rows = self._rows()
            wait = MAX_WAIT_SEC
            if rows:
                delta = (self._local(rows[0]["when_utc"]) - self.clock()).total_seconds()
                wait = max(0.05, min(wait, delta))
            self._changed.clear()
            try:
                await asyncio.wait_for(self._changed.wait(), wait)
            except asyncio.TimeoutError:
                pass

    async def fire_due(self) -> int:
        now = self.clock()
        fired = 0
        for r in self._rows():
            if self._local(r["when_utc"]) > now:
                break
            self._advance(r, now)
            sentence = due_sentence(r["message"])
            await self.announcer.notify("reminder", sentence, say=sentence)
            fired += 1
        if fired:
            await self.publish()
        return fired

    # ---- voice + tools ------------------------------------------------------------------

    async def handle(self, text: str, key: str, ctx: Context) -> str | None:
        """Local intent handler: set / list / cancel. Returns the reply, or None if not ours."""
        if re.search(r"(알림|리마인더|알람).*(취소|삭제|지워|없애|빼)", key):
            return await self._voice_cancel(text, key)
        if re.fullmatch(r"(리마인더|알림|알람)(뭐|뭐뭐|목록|몇개|있어|뭐있어|보여줘|알려줘|확인|뭐있지|있나)*(있어|야|지|요)?", key) or key in (
            "뭐알려주기로했지", "무슨알림있어", "알림있어"
        ):
            return self._voice_list(ctx.now)
        req = parse_reminder(text, ctx.now)
        if req is None:
            return None
        await self.create(req.when, req.message, req.repeat)
        when_words = spoken_when(req.when, ctx.now)
        if req.repeat:
            when_words = f"{repeat_label(req.repeat)} {spoken_time(req.when)}"
        elif req.relative:
            minutes = round((req.when - ctx.now).total_seconds() / 60)
            ahead = f"{minutes}분 뒤" if minutes < 60 else f"{minutes // 60}시간{f' {minutes % 60}분' if minutes % 60 else ''} 뒤"
            when_words = f"{ahead}인 {when_words}"
        if req.wake_up:
            return f"{when_words}에 깨워 드릴게요."
        what = "알려" if req.message == "알림" else f"{req.message}, 알려"
        return f"{when_words}에 {what}드릴게요."

    def _voice_list(self, now: datetime) -> str:
        items = self.pending()
        if not items:
            return "등록된 리마인더가 없어요."
        parts = []
        for r in items[:3]:
            when = datetime.fromisoformat(r["when"])
            label = f"{r['repeat']} {spoken_time(when)}" if r["repeat"] else spoken_when(when, now)
            parts.append(f"{label}에 {r['message']}")
        more = f" 외에 {len(items) - 3}개가 더 있어요." if len(items) > 3 else ""
        return f"리마인더가 {len(items)}개 있어요. " + ", ".join(parts) + "." + more

    async def _voice_cancel(self, text: str, key: str) -> str:
        items = self.pending()
        if not items:
            return "취소할 리마인더가 없어요."
        if re.search(r"(전부|모두|다)(취소|삭제|지워|없애)", key):
            for r in items:
                await self.cancel(r["id"])
            return f"리마인더 {len(items)}개를 모두 취소했어요."
        words = re.sub(r"(알림|리마인더|알람).*$", "", text).strip()
        words = re.sub(r"(을|를|이|가)$", "", words.strip())
        matches = self.find(words) if words else []
        if not matches and len(items) == 1 and not words:
            matches = items
        if len(matches) == 1:
            await self.cancel(matches[0]["id"])
            return f"{matches[0]['message']} 알림을 취소했어요."
        if not matches:
            return "어떤 알림인지 찾지 못했어요. 리마인더 목록을 먼저 확인해 보세요."
        return f"비슷한 알림이 {len(matches)}개 있어요. 조금 더 구체적으로 말씀해 주세요."

    def register_tools(self, tools: ToolRegistry) -> None:
        async def create_reminder(args: dict[str, Any]) -> dict[str, Any]:
            when = datetime.fromisoformat(args["when_iso"])
            if when.tzinfo is None:
                when = when.replace(tzinfo=self.clock().tzinfo)
            if when <= self.clock():
                return {"error": "that time is in the past"}
            repeat = None if args.get("repeat") in (None, "", "none") else args["repeat"]
            return await self.create(when, args["message"], repeat)

        async def list_reminders(_: dict[str, Any]) -> dict[str, Any]:
            return {"reminders": [{k: v for k, v in r.items() if k != "rule"} for r in self.pending()]}

        async def cancel_reminder(args: dict[str, Any]) -> dict[str, Any]:
            return {"cancelled": await self.cancel(int(args["id"]))}

        tools.register(
            Tool(
                "create_reminder",
                "리마인더를 만든다. when_iso는 KST 기준 ISO 8601 시각(예: 2026-09-29T16:30:00+09:00). "
                "repeat은 none | daily | weekdays | weekends | weekly:0,2 (0=월요일 … 6=일요일).",
                schema(
                    {
                        "when_iso": {"type": "string"},
                        "message": {"type": "string", "description": "알릴 내용, 짧은 명사구 (예: 과제 제출)"},
                        "repeat": {"type": "string"},
                    },
                    ["when_iso", "message", "repeat"],
                ),
                create_reminder,
            )
        )
        tools.register(Tool("list_reminders", "대기 중인 리마인더 목록을 조회한다.", schema(), list_reminders))
        tools.register(
            Tool(
                "cancel_reminder",
                "id로 리마인더를 취소한다. id는 list_reminders로 확인한다.",
                schema({"id": {"type": "integer"}}, ["id"]),
                cancel_reminder,
            )
        )
