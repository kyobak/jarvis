"""Local intents: frequent, fixed-shape commands answered without calling Claude.

Patterns match the *whole* utterance with spaces removed (STT spacing is unreliable),
so anything longer or ambiguous falls through to the LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from jarvis.brain.context import Context
from jarvis.core.korean import copula, join_and, topic
from jarvis.core.timeutil import spoken_time

WAKE_PREFIX = re.compile(r"^\s*(헤이|hey|하이|에이)?\s*(자비스|jarvis|쟈비스)[\s,.!?~]*", re.IGNORECASE)
PUNCT = re.compile(r"[\s.,!?~…·'\"“”‘’]+")
ENDINGS = r"(야|예요|에요|이에요|이야|지|이지|니|냐|인가요|인지|요|입니까|이죠|죠)?"
PLEASE = r"(알려줘|알려줘요|알려주세요|말해줘|말해줘요|좀)?"


def strip_wake(text: str) -> str:
    return WAKE_PREFIX.sub("", text).strip()


def squash(text: str) -> str:
    return PUNCT.sub("", text).lower()


@dataclass(frozen=True)
class LocalReply:
    intent: str
    text: str  # empty = acknowledge silently


@dataclass(frozen=True)
class Intent:
    name: str
    patterns: tuple[re.Pattern[str], ...]
    respond: Callable[[Context], str]


def _p(*regexes: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(f"^{r}$") for r in regexes)


def _time(ctx: Context) -> str:
    return f"지금은 {copula(spoken_time(ctx.now))}."


def _date(ctx: Context) -> str:
    return f"오늘은 {copula(ctx.date_line())}."


CAMERA_PHRASE = {
    "켜짐": "카메라는 켜져 있어요",
    "꺼짐": "카메라는 꺼져 있어요",
    "모의": "카메라는 모의 모드예요",
    "일시 중지": "카메라는 일시 중지 중이에요",
}
PROBLEM_PHRASE = {
    "연결 안 됨": "아직 연결 전이에요",
    "재인증 필요": "다시 연결해야 해요",
    "오프라인": "연결에 문제가 있어요",
    "오류": "연결에 문제가 있어요",
}


def _status(ctx: Context) -> str:
    summary = ctx.status_summary()
    sentences: list[str] = []
    if summary.get("camera") in CAMERA_PHRASE:
        sentences.append(CAMERA_PHRASE[summary["camera"]])

    by_problem: dict[str, list[str]] = {}
    for name, state in summary["integrations"].items():
        if state in PROBLEM_PHRASE:
            by_problem.setdefault(PROBLEM_PHRASE[state], []).append(name)
    if by_problem:
        for phrase, names in by_problem.items():
            sentences.append(f"{topic(join_and(names))} {phrase}")
    elif summary["integrations"]:
        sentences.append("연동은 모두 정상이에요")

    sentences.append(f"오늘 AI는 {summary.get('ai_calls_today', 0)}번 썼어요")
    return ". ".join(sentences) + "."


def _greeting(ctx: Context) -> str:
    h = ctx.now.hour
    hello = (
        "좋은 아침이에요" if 5 <= h < 11 else
        "안녕하세요" if 11 <= h < 17 else
        "좋은 저녁이에요" if 17 <= h < 23 else
        "늦은 시간이네요"
    )
    return f"{hello}, {ctx.user_name}님."


def _thanks(_: Context) -> str:
    return "천만에요."


def _dismiss(_: Context) -> str:
    return ""


DEFAULT_INTENTS: tuple[Intent, ...] = (
    Intent(
        "time",
        _p(
            rf"(지금|현재)?몇시{ENDINGS}",
            rf"(지금|현재)?시간{PLEASE}",
            rf"(지금|현재)?몇시{ENDINGS}{PLEASE}",
            rf"(지금|현재)?시간이?어떻게돼{ENDINGS}",
        ),
        _time,
    ),
    Intent(
        "date",
        _p(
            rf"오늘(이)?(며칠|몇월며칠|무슨요일|무슨날|날짜|요일){ENDINGS}{PLEASE}",
            rf"(날짜|요일){PLEASE}",
            rf"(오늘)?(날짜|요일)(가|이)?(뭐|어떻게돼){ENDINGS}",
        ),
        _date,
    ),
    Intent(
        "status",
        _p(
            rf"(시스템|연결|연동)?상태(는|가)?(어때|어때요|좀)?{PLEASE}",
            rf"(시스템|연결|연동)?상태(확인해줘|확인|보여줘)",
        ),
        _status,
    ),
    Intent("greeting", _p(r"(안녕|안녕하세요|하이|헬로|hello|hi)(자비스)?"), _greeting),
    Intent("thanks", _p(r"(고마워|고마워요|고맙습니다|감사해|감사해요|감사합니다|땡큐|thankyou|thanks)"), _thanks),
    Intent(
        "dismiss",
        _p(r"(아니|아니야|아니에요|됐어|됐어요|괜찮아|취소|그만|아무것도아니야|아무것도아니에요|잘못불렀어)"),
        _dismiss,
    ),
)


class IntentRouter:
    def __init__(self, intents: tuple[Intent, ...] = DEFAULT_INTENTS) -> None:
        self.intents = intents

    def match(self, text: str, ctx: Context) -> LocalReply | None:
        key = squash(strip_wake(text))
        if not key:
            return None
        for intent in self.intents:
            if any(p.match(key) for p in intent.patterns):
                return LocalReply(intent.name, intent.respond(ctx))
        return None
