"""Welcome-back and first-of-the-day greetings (F1), built locally — no LLM call."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable

from jarvis.core.announcer import Announcer
from jarvis.core.settings import Settings
from jarvis.core.timeutil import spoken_time

log = logging.getLogger(__name__)


def salutation(now: datetime) -> str:
    h = now.hour
    if 5 <= h < 11:
        return "좋은 아침이에요"
    if 11 <= h < 17:
        return "안녕하세요"
    if 17 <= h < 23:
        return "좋은 저녁이에요"
    return "늦은 시간이네요"


class Greeter:
    def __init__(
        self,
        announcer: Announcer,
        settings: Settings,
        clock: Callable[[], datetime],
        user_name: str,
        upcoming: Callable[[datetime], list[dict[str, Any]]],
        unread: Callable[[], dict[str, int]] | None = None,
        today_events: Callable[[datetime], list[dict[str, Any]]] | None = None,
    ) -> None:
        self.announcer = announcer
        self.settings = settings
        self.clock = clock
        self.user_name = user_name
        self.upcoming = upcoming
        self.unread = unread or (lambda: {})
        self.today_events = today_events
        self.last_greeted_day = None

    def _details(self, now: datetime) -> list[str]:
        parts = []
        nxt = self.upcoming(now)
        if nxt:
            e = nxt[0]
            mins = round((e["start"] - now).total_seconds() / 60)
            when = f"{mins}분 뒤에" if mins < 90 else f"{spoken_time(e['start'])}에"
            parts.append(f"{when} {e['title']} 일정이 있고")
        counts = self.unread()
        mail, slack = counts.get("gmail", 0), counts.get("slack", 0)
        news = []
        if mail:
            news.append(f"새 메일이 {mail}통")
        if slack:
            news.append(f"슬랙 메시지가 {slack}개")
        if news:
            parts.append(", ".join(news) + " 있어요")
        return parts

    def compose(self, now: datetime, first_today: bool) -> str:
        details = self._details(now)
        missed = self.announcer.take_missed()
        opening = f"{salutation(now)}, {self.user_name}님." if first_today else f"돌아오셨네요, {self.user_name}님."
        sentences = [opening]
        if first_today and self.today_events:
            events = [e for e in self.today_events(now) if not e.get("all_day")]
            if events:
                sentences.append(f"오늘 일정은 {len(events)}개예요.")
        if details:
            body = ", ".join(details)
            if not body.endswith("요"):
                body = body.removesuffix("있고") + "있어요"
            sentences.append(body + ".")
        if missed:
            sentences.append(f"자리 비운 사이에 알림이 {len(missed)}개 있었어요.")
        return " ".join(sentences)

    async def greet(self, reason: str) -> str | None:
        """reason: "return" (after an absence) or "arrive" (first sighting)."""
        if not self.settings["greeting"]:
            return None
        now = self.clock()
        first_today = self.last_greeted_day != now.date()
        self.last_greeted_day = now.date()
        text = self.compose(now, first_today and self.settings["daily_briefing"])
        if self.announcer.speaker and not self.settings.in_quiet_hours(now):
            await self.announcer.speaker(text, None)
        log.info("greeting (%s)", reason)
        return text
