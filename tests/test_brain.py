import asyncio

import pytest

from jarvis.brain.backends.base import LLMError, LLMResult, LLMRetryableError
from jarvis.brain.brain import LIMIT_REACHED, Brain
from jarvis.core.config import Config
from jarvis.core.db import Database
from jarvis.core.event_bus import EventBus
from jarvis.core.state import StateStore
from jarvis.core.status import StatusBoard


class FakeBackend:
    name = "fake"
    label = "Fake"

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.resets = 0

    def availability(self):
        return "ok"

    def reset(self):
        self.resets += 1

    async def respond(self, utterance, ctx):
        self.calls.append(utterance)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_brain(backend, limit=200_000):
    config = Config()
    config.llm.daily_token_limit = limit
    bus = EventBus()
    db = Database(":memory:")
    return Brain(config, StateStore(bus), db, StatusBoard(bus), backend), db


@pytest.fixture(autouse=True)
def fast_retry(monkeypatch):
    monkeypatch.setattr("jarvis.brain.brain.RETRY_DELAY_SEC", 0)


async def test_local_intent_skips_llm():
    backend = FakeBackend()
    brain, _ = make_brain(backend)
    reply = await brain.handle("헤이 자비스 지금 몇 시야")
    assert reply.source == "local" and reply.intent == "time"
    assert backend.calls == []


async def test_llm_reply_records_usage():
    backend = FakeBackend(LLMResult("된장찌개 어떠세요?", 100, 20))
    brain, db = make_brain(backend)
    reply = await brain.handle("저녁 뭐 먹지")
    assert reply == type(reply)("된장찌개 어떠세요?", "llm")
    assert backend.calls == ["저녁 뭐 먹지"]
    usage = db.llm_usage(brain.clock().date())
    assert usage == {"calls": 1, "input_tokens": 100, "output_tokens": 20}
    assert brain.status.data["llm"]["tokens"] == 120


async def test_retry_once_then_apologise():
    backend = FakeBackend(LLMRetryableError("net"), LLMResult("ok", 1, 1))
    brain, _ = make_brain(backend)
    assert (await brain.handle("질문")).text == "ok"

    backend = FakeBackend(LLMRetryableError("net"), LLMRetryableError("net"))
    brain, _ = make_brain(backend)
    reply = await brain.handle("질문")
    assert reply.source == "error" and "인터넷" in reply.text
    assert len(backend.calls) == 2


async def test_backend_error_message_is_spoken():
    brain, _ = make_brain(FakeBackend(LLMError("x", "Claude Code 로그인이 필요해요.")))
    assert (await brain.handle("질문")).text == "Claude Code 로그인이 필요해요."


async def test_daily_limit_blocks_llm_but_not_local():
    backend = FakeBackend()
    brain, db = make_brain(backend, limit=100)
    db.record_llm_usage(brain.clock().date(), 90, 20)
    assert (await brain.handle("질문")).text == LIMIT_REACHED
    assert (await brain.handle("몇 시야")).source == "local"
    assert backend.calls == []


async def test_history_resets_after_idle(monkeypatch):
    backend = FakeBackend(LLMResult("a"), LLMResult("b"), LLMResult("c"))
    brain, _ = make_brain(backend)
    clock = [1000.0]
    monkeypatch.setattr("jarvis.brain.brain.time.monotonic", lambda: clock[0])
    await brain.handle("첫 질문")
    clock[0] += 60
    await brain.handle("이어서")
    assert backend.resets == 0
    clock[0] += 6 * 60
    await brain.handle("한참 뒤")
    assert backend.resets == 1


async def test_empty_after_wake_word():
    brain, _ = make_brain(FakeBackend())
    assert (await brain.handle("헤이 자비스")).source == "none"


async def test_llm_calls_are_serialised():
    order = []

    class Slow(FakeBackend):
        async def respond(self, utterance, ctx):
            order.append(("start", utterance))
            await asyncio.sleep(0.01)
            order.append(("end", utterance))
            return LLMResult(utterance)

    brain, _ = make_brain(Slow())
    await asyncio.gather(brain.handle("하나"), brain.handle("둘"))
    assert order[1][0] == "end"
