"""Korean time expressions for reminders: "4시 반에", "30분 뒤에", "내일 아침 7시",
"매일 밤 12시", "평일 9시", "매주 월요일 10시".

Ambiguous hours without 오전/오후 resolve to the nearest future time (plan §6.3);
on another day, 1–6시 means afternoon and 7–11시 morning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

WEEKDAY_CHARS = "월화수목금토일"
NATIVE_NUMBERS = {
    "한": 1, "하나": 1, "두": 2, "둘": 2, "세": 3, "셋": 3, "네": 4, "넷": 4, "다섯": 5, "여섯": 6,
    "일곱": 7, "여덟": 8, "아홉": 9, "열": 10, "열한": 11, "열하나": 11, "열두": 12, "열둘": 12,
    "스무": 20, "스물": 20, "서른": 30, "마흔": 40, "쉰": 50,
}
SINO_NUMBERS = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9, "십": 10}
NUM = r"(\d+|열두|열둘|열한|열하나|하나|다섯|여섯|일곱|여덟|아홉|스무|스물|서른|마흔|쉰|한|두|둘|세|셋|네|넷|열|십|이십|삼십|사십|오십)"
PERIODS = r"(오전|오후|아침|낮|점심|저녁|밤|새벽)"

REPEAT_RE = re.compile(
    rf"(매일|날마다|평일(?:마다)?|주말(?:마다)?|매주\s*([{WEEKDAY_CHARS}](?:\s*,?\s*[{WEEKDAY_CHARS}])*)요일|"
    rf"([{WEEKDAY_CHARS}])요일마다)"
)
DAY_RE = re.compile(r"(오늘|내일|모레|글피)")
WEEKDAY_RE = re.compile(rf"(이번\s*주|다음\s*주|담주)?\s*([{WEEKDAY_CHARS}])요일")
RELATIVE_RE = re.compile(
    rf"((?:{NUM}\s*(?:시간|분|초)\s*(?:반)?\s*)+)(?:뒤|후|있다가|이따가|지나서)(?:에)?"
)
ABSOLUTE_RE = re.compile(
    rf"(?:{PERIODS}\s*)?(?:{NUM}\s*시(?!간)\s*(?:(반)|(\d+)\s*분|정각)?|(자정|정오))(?:\s*에)?"
)
TAIL = r"(하라고|하라는|해야\s*한다고|이라고|으라고|라고)"
REQUEST_RE = re.compile(
    rf"\s*(?:{TAIL}\s*)?(?:꼭\s*)?(?:좀\s*)?"
    r"(알려\s*줘요?|알려\s*주세요|알려\s*줄래|알려\s*줄\s*수\s*있어|말해\s*줘요?|말해\s*주세요|"
    r"알림\s*(?:좀\s*)?(?:맞춰|설정해|해|등록해)\s*(?:줘|주세요)|리마인드\s*해\s*줘|리마인더\s*(?:맞춰|설정해)\s*줘|"
    r"깨워\s*줘요?|깨워\s*주세요)\s*[.!?~]*\s*$"
)
# "빨래 꺼내라고 해줘": plain 해줘 only counts after a quoting tail.
QUOTED_REQUEST_RE = re.compile(rf"\s*{TAIL}\s*(?:꼭\s*)?(?:좀\s*)?(해\s*줘요?|해\s*주세요|말해\s*줄래)\s*[.!?~]*\s*$")
# Final syllables of common verb stems before imperative -라고 (가라고, 꺼내라고, 마시라고);
# anything else is treated as a noun ("스터디라고" stays "스터디").
VERB_STEM_ENDINGS = set("가오내자사서켜끄쉬시치보두주매개빼세뜨타쓰우르")


def to_int(token: str) -> int:
    if token.isdigit():
        return int(token)
    if token in NATIVE_NUMBERS:
        return NATIVE_NUMBERS[token]
    # 이십, 삼십 …
    if token.endswith("십") and token[:-1] in SINO_NUMBERS:
        return SINO_NUMBERS[token[:-1]] * 10
    return SINO_NUMBERS.get(token, 0)


@dataclass
class ParsedTime:
    when: datetime  # next occurrence (tz-aware)
    repeat: str | None  # daily | weekdays | weekends | weekly:0,2 (Mon=0)
    relative: bool  # "30분 뒤" style
    rest: str  # the utterance with time words removed


@dataclass
class ReminderRequest:
    when: datetime
    repeat: str | None
    relative: bool
    message: str
    wake_up: bool  # "깨워줘"


def _hour24(hour: int, period: str | None) -> int | None:
    """Clock hour for an explicit period, or None when it needs the ambiguity rule."""
    if period in ("오전", "아침", "새벽"):
        return 0 if hour == 12 else hour
    if period in ("오후", "저녁"):
        return hour if hour == 12 else hour + 12
    if period in ("낮", "점심"):
        return hour + 12 if hour <= 6 else hour
    if period == "밤":
        if hour == 12:
            return 0
        return hour + 12 if hour >= 6 else hour
    return None


def repeat_label(rule: str | None) -> str | None:
    if not rule:
        return None
    if rule == "daily":
        return "매일"
    if rule == "weekdays":
        return "평일"
    if rule == "weekends":
        return "주말"
    if rule.startswith("weekly:"):
        days = [WEEKDAY_CHARS[int(d)] for d in rule[7:].split(",") if d]
        return "매주 " + "·".join(days)
    return rule


def matches_rule(rule: str, d: date) -> bool:
    wd = d.weekday()
    if rule == "daily":
        return True
    if rule == "weekdays":
        return wd < 5
    if rule == "weekends":
        return wd >= 5
    if rule.startswith("weekly:"):
        return str(wd) in rule[7:].split(",")
    return False


def next_occurrence(rule: str, clock_time: time, after: datetime) -> datetime:
    """First datetime strictly after `after` at `clock_time` on a day matching `rule`."""
    day = after.date()
    for _ in range(8):
        candidate = datetime.combine(day, clock_time, tzinfo=after.tzinfo)
        if candidate > after and matches_rule(rule, day):
            return candidate
        day += timedelta(days=1)
    raise ValueError(f"no occurrence for rule {rule!r}")


def _parse_repeat(m: re.Match[str]) -> str:
    word = m.group(1)
    if word.startswith(("매일", "날마다")):
        return "daily"
    if word.startswith("평일"):
        return "weekdays"
    if word.startswith("주말"):
        return "weekends"
    chars = m.group(2) or m.group(3) or ""
    days = sorted({WEEKDAY_CHARS.index(c) for c in chars if c in WEEKDAY_CHARS})
    return "weekly:" + ",".join(map(str, days))


def parse_time(text: str, now: datetime) -> ParsedTime | None:
    """Find the reminder time in `text`. Returns None if there is no time expression."""
    rest = text
    repeat = None
    m = REPEAT_RE.search(rest)
    if m:
        repeat = _parse_repeat(m)
        rest = rest[: m.start()] + " " + rest[m.end() :]

    rel = RELATIVE_RE.search(rest)
    if rel and not repeat:
        total = timedelta()
        for num, unit, half in re.findall(rf"{NUM}\s*(시간|분|초)\s*(반)?", rel.group(1)):
            n = to_int(num)
            step = {"시간": timedelta(hours=1), "분": timedelta(minutes=1), "초": timedelta(seconds=1)}[unit]
            total += step * n + (step / 2 if half else timedelta())
        if total <= timedelta():
            return None
        rest = rest[: rel.start()] + " " + rest[rel.end() :]
        return ParsedTime(now + total, None, True, _clean(rest))

    day_offset = None
    target_weekday = None
    d = DAY_RE.search(rest)
    if d:
        day_offset = {"오늘": 0, "내일": 1, "모레": 2, "글피": 3}[d.group(1)]
        rest = rest[: d.start()] + " " + rest[d.end() :]
    elif not repeat:
        w = WEEKDAY_RE.search(rest)
        if w:
            target_weekday = WEEKDAY_CHARS.index(w.group(2))
            next_week = bool(w.group(1) and w.group(1).replace(" ", "") in ("다음주", "담주"))
            rest = rest[: w.start()] + " " + rest[w.end() :]
            day_offset = (target_weekday - now.weekday()) % 7
            if next_week:
                day_offset += 7 if day_offset else 7

    a = ABSOLUTE_RE.search(rest)
    if not a:
        return None
    period, hour_tok, half, minute_tok, named = a.group(1), a.group(2), a.group(3), a.group(4), a.group(5)
    rest = rest[: a.start()] + " " + rest[a.end() :]
    if named:
        hour, minute, period = (0, 0, "오전") if named == "자정" else (12, 0, "오후")
    else:
        hour = to_int(hour_tok)
        minute = 30 if half else int(minute_tok) if minute_tok else 0
    if not (0 <= hour <= 24 and 0 <= minute < 60):
        return None
    if hour == 24:
        hour = 0

    explicit = _hour24(hour, period) if hour <= 12 else hour
    if repeat:
        h = explicit if explicit is not None else hour
        when = next_occurrence(repeat, time(h % 24, minute), now)
        return ParsedTime(when, repeat, False, _clean(rest))

    if day_offset is None:
        base = now.date()
        if explicit is not None:
            candidates = [explicit]
        elif hour == 12:
            candidates = [12, 0]
        else:
            candidates = [hour, hour + 12]
        options = []
        for h in candidates:
            dt = datetime.combine(base, time(h % 24, minute), tzinfo=now.tzinfo)
            while dt <= now:
                dt += timedelta(days=1)
            options.append(dt)
        return ParsedTime(min(options), None, False, _clean(rest))

    if explicit is None:
        explicit = hour + 12 if 1 <= hour <= 6 else hour % 24
    day = now.date() + timedelta(days=day_offset)
    when = datetime.combine(day, time(explicit % 24, minute), tzinfo=now.tzinfo)
    if when <= now:
        if target_weekday is not None:
            when += timedelta(days=7)
        else:
            return None  # "오늘 아침 7시" said at noon: in the past
    return ParsedTime(when, None, False, _clean(rest))


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" ,.")


def parse_reminder(text: str, now: datetime) -> ReminderRequest | None:
    """Parse a whole reminder request, or None if this is not one."""
    req = REQUEST_RE.search(text) or QUOTED_REQUEST_RE.search(text)
    if not req:
        return None
    body = text[: req.start()]
    tail = req.group(1) or ""
    verb = req.group(2)
    parsed = parse_time(body, now)
    if parsed is None:
        return None
    message = parsed.rest.strip()
    message = re.sub(r"^(에|에는|쯤|쯤에)\s+", "", message)
    message = re.sub(r"\s*(을|를)$", "", message)
    wake = verb.replace(" ", "").startswith("깨워")
    tail = tail.replace(" ", "")
    if message and (tail == "으라고" or (tail == "라고" and message[-1] in VERB_STEM_ENDINGS)):
        # "빨래 꺼내라고" → "빨래 꺼내기", "약 먹으라고" → "약 먹기": a bare verb stem becomes a noun.
        message += "기"
    if not message:
        message = "일어나기" if wake else "알림"
    return ReminderRequest(parsed.when, parsed.repeat, parsed.relative, message, wake)
