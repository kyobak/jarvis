"""Turns an utterance into a spoken reply: local intents first, Claude only when needed."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from jarvis.brain.backends.base import LLMBackend, LLMError, LLMRetryableError
from jarvis.brain.context import Context
from jarvis.brain.router import IntentRouter, strip_wake
from jarvis.core.config import Config
from jarvis.core.db import Database
from jarvis.core.state import StateStore
from jarvis.core.status import StatusBoard

log = logging.getLogger(__name__)

LIMIT_REACHED = "오늘 AI 사용량을 다 썼어요. 시간이나 날짜 같은 기본 명령은 계속 쓸 수 있어요."
RETRY_DELAY_SEC = 1.0


@dataclass(frozen=True)
class Reply:
    text: str
    source: str  # local | llm | limit | error | none
    intent: str | None = None


class Brain:
    def __init__(
        self,
        config: Config,
        store: StateStore,
        db: Database,
        status: StatusBoard,
        backend: LLMBackend,
        router: IntentRouter | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.db = db
        self.status = status
        self.backend = backend
        self.router = router or IntentRouter()
        self.clock = clock or (lambda: datetime.now(config.tz))
        self._last_llm_at = 0.0
        self._lock = asyncio.Lock()

    def context(self) -> Context:
        personal = self.config.llm.personal_data_allowed(self.backend.name)
        return Context.build(self.store, self.clock(), self.config.user_name, personal)

    async def publish_usage(self) -> None:
        usage = self.db.llm_usage(self.clock().date())
        await self.status.update(
            llm={
                "calls": usage["calls"],
                "tokens": usage["input_tokens"] + usage["output_tokens"],
                "limit": self.config.llm.daily_token_limit,
                "backend": self.backend.name,
                "label": self.backend.label,
            },
            integrations={"ai": self.backend.availability()},
        )

    async def handle(self, utterance: str) -> Reply:
        text = strip_wake(utterance)
        if not text:
            return Reply("", "none")
        ctx = self.context()

        local = self.router.match(text, ctx)
        if local is not None:
            log.info("local intent %s", local.intent)
            return Reply(local.text, "local", local.intent)

        async with self._lock:  # one LLM conversation at a time
            return await self._ask_llm(text, ctx)

    async def _ask_llm(self, text: str, ctx: Context) -> Reply:
        today = ctx.now.date()
        usage = self.db.llm_usage(today)
        if usage["input_tokens"] + usage["output_tokens"] >= self.config.llm.daily_token_limit:
            return Reply(LIMIT_REACHED, "limit")

        idle_for = time.monotonic() - self._last_llm_at
        if self._last_llm_at and idle_for > self.config.llm.history_reset_min * 60:
            self.backend.reset()

        try:
            try:
                result = await self.backend.respond(text, ctx)
            except LLMRetryableError as e:
                log.warning("LLM call failed, retrying once: %s", e)
                await asyncio.sleep(RETRY_DELAY_SEC)
                result = await self.backend.respond(text, ctx)
        except LLMError as e:
            return Reply(e.user_message, "error")

        self._last_llm_at = time.monotonic()
        if self.backend.name != "mock":
            self.db.record_llm_usage(today, result.input_tokens, result.output_tokens)
            await self.publish_usage()
        return Reply(result.text, "llm")
