"""Snapshot of the app state that the brain and local intents reason about."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from jarvis.core.state import StateStore
from jarvis.core.timeutil import WEEKDAYS_KO, spoken_time

LINK_KO = {
    "ok": "연결됨",
    "mock": "모의",
    "offline": "오프라인",
    "expired": "재인증 필요",
    "disabled": "연결 안 됨",
    "error": "오류",
    "on": "켜짐",
    "off": "꺼짐",
    "paused": "일시 중지",
}
INTEGRATION_KO = {
    "calendar": "캘린더",
    "gmail": "Gmail",
    "slack": "Slack",
    "spotify": "Spotify",
    "ai": "AI",
}


@dataclass
class Context:
    now: datetime
    user_name: str
    status: dict[str, Any]
    next_event: dict[str, Any] | None
    focus_session: dict[str, Any] | None
    # False when the LLM is a free tier that may train on inputs: prompts then omit
    # schedule titles and other personal content (llm.send_personal_data).
    personal: bool = True

    @classmethod
    def build(cls, store: StateStore, now: datetime, user_name: str, personal: bool = True) -> "Context":
        schedule = store.get("schedule") or {}
        upcoming = [
            e for e in schedule.get("events", []) if datetime.fromisoformat(e["start"]) > now
        ]
        upcoming.sort(key=lambda e: e["start"])
        focus = store.get("focus") or {}
        return cls(
            now=now,
            user_name=user_name,
            status=store.get("status") or {},
            next_event=upcoming[0] if upcoming else None,
            focus_session=focus.get("session"),
            personal=personal,
        )

    def date_line(self) -> str:
        n = self.now
        return f"{n.month}월 {n.day}일 {WEEKDAYS_KO[n.weekday()]}요일"

    def prompt_block(self) -> str:
        """Compact situational context prepended to each LLM request."""
        n = self.now
        lines = [f"현재 시각: {n:%Y-%m-%d} ({WEEKDAYS_KO[n.weekday()]}) {n:%H:%M} KST"]
        if self.next_event:
            start = datetime.fromisoformat(self.next_event["start"])
            mins = int((start - n).total_seconds() // 60)
            title = f" {self.next_event['title']}" if self.personal else ""
            lines.append(f"다음 일정: {start:%H:%M}{title} ({mins}분 후)")
        else:
            lines.append("다음 일정: 없음")
        if self.focus_session:
            lines.append("집중 모드: 진행 중")
        else:
            lines.append("집중 모드: 꺼짐")
        return "\n".join(lines)

    def status_summary(self) -> dict[str, Any]:
        st = self.status
        integrations = st.get("integrations", {})
        llm = st.get("llm", {})
        return {
            "camera": LINK_KO.get(st.get("camera", ""), st.get("camera")),
            "mic": LINK_KO.get(st.get("mic", ""), st.get("mic")),
            "integrations": {
                INTEGRATION_KO.get(k, k): LINK_KO.get(v, v) for k, v in integrations.items()
            },
            "ai_calls_today": llm.get("calls", 0),
            "ai_tokens_today": llm.get("tokens", 0),
            "ai_daily_token_limit": llm.get("limit"),
            "time": spoken_time(self.now),
        }
