"""Anthropic Messages API backend (billed per token, needs ANTHROPIC_API_KEY)."""

from __future__ import annotations

import logging
import os
from typing import Any

import anthropic

from jarvis.brain.backends.base import LLMError, LLMResult, LLMRetryableError
from jarvis.brain.context import Context
from jarvis.brain.prompts import system_prompt, user_turn
from jarvis.brain.tools import ToolRegistry
from jarvis.core.config import LLMConfig

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 4


class ApiBackend:
    name = "api"

    def __init__(self, config: LLMConfig, tools: ToolRegistry, user_name: str, client: Any = None) -> None:
        self.config = config
        self.tools = tools
        self.system = system_prompt(user_name)
        # Retries are handled by the brain (one retry, then a spoken apology).
        self.client = client or anthropic.AsyncAnthropic(timeout=config.timeout_sec, max_retries=0)
        self.history: list[dict[str, Any]] = []

    def availability(self) -> str:
        return "ok" if os.environ.get("ANTHROPIC_API_KEY") else "error"

    def reset(self) -> None:
        self.history.clear()

    async def respond(self, utterance: str, ctx: Context) -> LLMResult:
        turn = {"role": "user", "content": user_turn(ctx, utterance)}
        messages: list[dict[str, Any]] = [*self.history, turn]
        result = LLMResult("")

        for _ in range(MAX_TOOL_ROUNDS + 1):
            response = await self._create(messages)
            result.input_tokens += response.usage.input_tokens
            result.output_tokens += response.usage.output_tokens

            if response.stop_reason == "refusal":
                result.text = "그 요청은 도와드리기 어려워요."
                break
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not tool_uses:
                result.text = "".join(b.text for b in response.content if b.type == "text").strip()
                break

            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in tool_uses:
                content, is_error = await self.tools.call(block.name, block.input)
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": content, "is_error": is_error}
                )
            messages.append({"role": "user", "content": results})
        else:
            result.text = "요청을 처리하는 데 단계가 너무 많이 필요해서 멈췄어요."

        if not result.text:
            result.text = "죄송해요, 뭐라고 답해야 할지 모르겠어요."
        self._remember(turn, result.text)
        return result

    def _remember(self, turn: dict[str, Any], answer: str) -> None:
        # Keep plain text only; tool traffic is not needed for follow-up questions.
        self.history += [turn, {"role": "assistant", "content": answer}]
        keep = self.config.history_turns * 2
        self.history = self.history[-keep:]

    async def _create(self, messages: list[dict[str, Any]]) -> Any:
        try:
            return await self.client.messages.create(
                model=self.config.default_model,
                max_tokens=self.config.max_tokens,
                system=self.system,
                tools=self.tools.for_messages_api(),
                messages=messages,
            )
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
            raise LLMError(str(e), "Claude API 키를 확인해 주세요.") from e
        except anthropic.RateLimitError as e:
            raise LLMRetryableError(str(e)) from e
        except anthropic.APIConnectionError as e:  # includes timeouts
            raise LLMRetryableError(str(e)) from e
        except anthropic.APIStatusError as e:
            if e.status_code >= 500:
                raise LLMRetryableError(str(e)) from e
            log.error("Claude API error %s: %s", e.status_code, e.message)
            raise LLMError(str(e)) from e
