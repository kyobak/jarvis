"""Backends that never reach Claude: `off` (local intents only) and `mock` (demo)."""

from __future__ import annotations

import asyncio

from jarvis.brain.backends.base import LLMError, LLMResult
from jarvis.brain.context import Context


class OffBackend:
    name = "off"

    def availability(self) -> str:
        return "disabled"

    async def respond(self, utterance: str, ctx: Context) -> LLMResult:
        raise LLMError(
            "llm backend is off",
            "AI 연결이 꺼져 있어서 그건 답하기 어려워요. 시간이나 날짜, 상태 같은 기본 명령은 쓸 수 있어요.",
        )

    def reset(self) -> None:
        pass


class MockBackend:
    name = "mock"

    def __init__(self, delay: float = 0.9) -> None:
        self.delay = delay
        self.turns = 0

    def availability(self) -> str:
        return "mock"

    async def respond(self, utterance: str, ctx: Context) -> LLMResult:
        await asyncio.sleep(self.delay)
        self.turns += 1
        return LLMResult(f"모의 모드라 AI 대신 답해요. “{utterance}”라고 하셨죠?", 120, 30)

    def reset(self) -> None:
        self.turns = 0
