from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
WEEKDAYS_KO = ["월", "화", "수", "목", "금", "토", "일"]


def now(tz: ZoneInfo = KST) -> datetime:
    return datetime.now(tz)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def epoch_ms(dt: datetime | None = None) -> int:
    return int((dt or datetime.now().astimezone()).timestamp() * 1000)


def spoken_time(dt: datetime) -> str:
    """Korean spoken form, e.g. "오후 9시 47분"."""
    period = "오전" if dt.hour < 12 else "오후"
    hour = dt.hour % 12 or 12
    minute = f" {dt.minute}분" if dt.minute else ""
    return f"{period} {hour}시{minute}"
