from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from jarvis.brain.context import Context


@dataclass
class LLMResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class LLMError(Exception):
    """Failure with a short Korean sentence the assistant can say out loud."""

    def __init__(self, message: str, user_message: str = "죄송해요, 답을 만드는 중에 문제가 생겼어요.") -> None:
        super().__init__(message)
        self.user_message = user_message


class LLMRetryableError(LLMError):
    """Network trouble, timeouts, overload: worth one retry."""

    def __init__(self, message: str) -> None:
        super().__init__(message, "인터넷 연결이 불안정해서 답을 받지 못했어요.")


class LLMBackend(Protocol):
    name: str
    label: str  # shown in the UI, e.g. "Gemini"

    def availability(self) -> str:
        """Status chip value: ok | error | disabled | mock."""
        ...

    async def respond(self, utterance: str, ctx: Context, use_tools: bool = True) -> LLMResult:
        """use_tools=False: no tools and no conversation memory (for untrusted content)."""
        ...

    def reset(self) -> None:
        """Forget the conversation."""
        ...
