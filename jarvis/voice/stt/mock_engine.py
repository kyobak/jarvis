from __future__ import annotations

import itertools
import time

# Mix of local intents and one that needs the LLM.
PHRASES = ("지금 몇 시야?", "오늘 며칠이야?", "시스템 상태 어때?", "오늘 저녁 메뉴 추천해 줄래?")


class MockEngine:
    name = "mock"

    def __init__(self, phrases: tuple[str, ...] = PHRASES, delay: float = 0.4) -> None:
        self._phrases = itertools.cycle(phrases)
        self.delay = delay

    def check(self) -> None:
        pass

    def load(self) -> None:
        pass

    def transcribe(self, pcm16: bytes) -> str:
        time.sleep(self.delay)
        return next(self._phrases)
