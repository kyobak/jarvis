"""Believable fake content, generated relative to the current time."""

from __future__ import annotations

import itertools
import random
from datetime import datetime, timedelta

from jarvis.core.timeutil import iso

TRACKS = [
    {"title": "Moonlight Drive", "artist": "Seoul Lo-fi Club", "album": "Late Library", "duration_ms": 214_000, "hue": 196},
    {"title": "Blue in Green", "artist": "Quiet Quartet", "album": "Night Sessions", "duration_ms": 337_000, "hue": 222},
    {"title": "Paper Planes", "artist": "Haneul", "album": "Dormitory Window", "duration_ms": 188_000, "hue": 168},
    {"title": "Soft Rain on Tin", "artist": "Kōen", "album": "Study Weather", "duration_ms": 243_000, "hue": 205},
    {"title": "Afterglow", "artist": "Midnight Transit", "album": "Line 2", "duration_ms": 261_000, "hue": 32},
]

INCOMING = itertools.cycle(
    [
        ("gmail", "학사팀", "[공지] 2학기 수강 정정 기간 안내", "수강 정정은 10월 2일까지 포털에서 가능합니다."),
        ("slack", "민지", "#umc-스터디", "재원님 내일 발표 자료 공유 부탁드려요!"),
        ("gmail", "GitHub", "[kyobak/jarvis] New star", "Someone starred your repository."),
        ("slack", "도현", "DM", "오늘 헬스 갈 거야? 8시 어때"),
        ("gmail", "도서관", "대출 도서 반납 예정일 안내", "대출하신 도서의 반납 예정일은 10월 1일입니다."),
    ]
)


def schedule(now: datetime) -> list[dict]:
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    def at(delta: timedelta, minutes: int) -> datetime:
        return (now + delta).replace(second=0, microsecond=0) + timedelta(minutes=minutes)

    events = [
        ("알고리즘 강의", at(timedelta(hours=-5), 0), 75),
        ("점심 — 학생식당", at(timedelta(hours=-3, minutes=-10), 0), 45),
        ("운영체제 과제", at(timedelta(hours=-1, minutes=-20), 0), 60),
        ("UMC 스터디", at(timedelta(minutes=40), 0), 90),
        ("헬스", at(timedelta(hours=2, minutes=40), 0), 60),
        ("과제 마감 — 데이터베이스", at(timedelta(hours=4), 0), 0),
    ]
    out = []
    for i, (title, start, dur) in enumerate(events):
        # Keep the demo day inside "today" so the timeline reads naturally.
        if start.date() != today.date():
            continue
        out.append(
            {
                "id": f"mock-ev-{i}",
                "title": title,
                "start": iso(start),
                "end": iso(start + timedelta(minutes=dur)),
                "calendar": "primary",
            }
        )
    return out


async def seed_reminders(service, now: datetime) -> None:
    """Demo reminders for mock mode (its database is in memory)."""
    if service.pending():
        return
    await service.create((now + timedelta(minutes=25)).replace(second=0, microsecond=0), "빨래 꺼내기")
    bedtime = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    await service.create(bedtime, "잘 준비", "daily")


def messages(now: datetime) -> dict:
    def ago(minutes: int) -> str:
        return iso(now - timedelta(minutes=minutes))

    return {
        "gmail": {
            "auth": "ok",
            "items": [
                {"id": "g1", "sender": "김교수님", "subject": "운영체제 과제 3 공지", "snippet": "과제 3의 제출 기한은 금요일 23:59입니다.", "received_at": ago(12)},
                {"id": "g2", "sender": "장학팀", "subject": "교내 장학금 신청 안내", "snippet": "신청 기간은 이번 주까지입니다.", "received_at": ago(58)},
                {"id": "g3", "sender": "Notion", "subject": "주간 요약", "snippet": "이번 주 편집한 페이지 6개", "received_at": ago(140)},
            ],
        },
        "slack": {
            "auth": "ok",
            "items": [
                {"id": "s1", "sender": "팀장 서연", "subject": "#umc-프로젝트", "snippet": "회의 시간 8시로 옮길게요", "received_at": ago(20)},
            ],
        },
    }


def focus_week(now: datetime) -> list[dict]:
    rng = random.Random(now.date().toordinal())
    days = []
    for back in range(6, -1, -1):
        d = (now - timedelta(days=back)).date()
        minutes = 200 if back == 0 else rng.randint(60, 320)
        days.append({"date": d.isoformat(), "min": minutes})
    return days
