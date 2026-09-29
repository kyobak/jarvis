"""Any OpenAI-compatible chat API: Gemini (free tier, default), Groq, OpenRouter,
GitHub Models, Ollama, or a custom endpoint. Same manual tool loop as the Claude
API backend, speaking the Chat Completions wire format over httpx2."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Mapping

import httpx2

from jarvis.brain.backends.base import LLMError, LLMResult, LLMRetryableError
from jarvis.brain.context import Context
from jarvis.brain.prompts import system_prompt, user_turn
from jarvis.brain.tools import ToolRegistry
from jarvis.core.config import LLMConfig

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 4


@dataclass(frozen=True)
class Preset:
    label: str
    base_url: str
    key_env: str | None  # None = no key needed (local server)
    model: str | None  # None = the user must set llm.openai_compat.model


# Free tiers and model names change often; verify at sign-up (docs/setup.md 3).
PRESETS: dict[str, Preset] = {
    "gemini": Preset(
        "Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY", "gemini-flash-latest"
    ),
    "groq": Preset("Groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY", None),
    "openrouter": Preset("OpenRouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", None),
    "github": Preset("GitHub Models", "https://models.github.ai/inference", "GITHUB_TOKEN", None),
    "ollama": Preset("Ollama", "http://127.0.0.1:11434/v1", None, None),
    "custom": Preset("AI", "", "OPENAI_COMPAT_API_KEY", None),
}


def function_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Loosen a strict JSON schema for providers with partial JSON-schema support (e.g. Gemini)."""
    out = {k: v for k, v in schema.items() if k != "additionalProperties"}
    if not out.get("required"):
        out.pop("required", None)
    if "properties" in out:
        out["properties"] = {k: function_schema(v) if isinstance(v, dict) else v for k, v in out["properties"].items()}
    return out


class OpenAICompatBackend:
    name = "openai_compat"

    def __init__(
        self,
        config: LLMConfig,
        tools: ToolRegistry,
        user_name: str,
        client: httpx2.AsyncClient | None = None,
        env: Mapping[str, str] = os.environ,
    ) -> None:
        self.config = config
        cfg = config.openai_compat
        preset = PRESETS[cfg.provider]
        self.label = preset.label
        self.base_url = (cfg.base_url or preset.base_url).rstrip("/")
        self.model = cfg.model or preset.model
        key_env = cfg.api_key_env or preset.key_env
        self.key_env = key_env
        self.api_key = env.get(key_env, "") if key_env else ""
        self.tools = tools
        self.system = system_prompt(user_name)
        self.client = client or httpx2.AsyncClient(timeout=config.timeout_sec)
        self.history: list[dict[str, Any]] = []

    def problem(self) -> str | None:
        """Why this backend cannot run, or None."""
        if not self.base_url:
            return "llm.openai_compat.base_url is not set"
        if not self.model:
            return f"llm.openai_compat.model is not set (required for {self.label})"
        if self.key_env and not self.api_key:
            return f"{self.key_env} is not set"
        return None

    def availability(self) -> str:
        return "ok" if self.problem() is None else "error"

    def reset(self) -> None:
        self.history.clear()

    def _tool_specs(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": function_schema(t["input_schema"]),
                },
            }
            for t in self.tools.describe()
        ]

    async def respond(self, utterance: str, ctx: Context) -> LLMResult:
        turn = {"role": "user", "content": user_turn(ctx, utterance)}
        messages: list[dict[str, Any]] = [{"role": "system", "content": self.system}, *self.history, turn]
        result = LLMResult("")

        for _ in range(MAX_TOOL_ROUNDS + 1):
            data = await self._post(messages)
            usage = data.get("usage") or {}
            result.input_tokens += int(usage.get("prompt_tokens") or 0)
            result.output_tokens += int(usage.get("completion_tokens") or 0)

            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            finish = choice.get("finish_reason")
            calls = message.get("tool_calls") or []
            if finish == "content_filter":
                result.text = "그 요청은 도와드리기 어려워요."
                break
            if not calls:
                result.text = (message.get("content") or "").strip()
                if not result.text and finish == "length":
                    result.text = "생각이 길어져서 답을 끝내지 못했어요. 조금 더 짧게 물어봐 주세요."
                break

            messages.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": calls})
            for i, call in enumerate(calls):
                fn = call.get("function") or {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                    content, _ = await self.tools.call(str(fn.get("name")), args if isinstance(args, dict) else {})
                except json.JSONDecodeError:
                    content = json.dumps({"error": "arguments were not valid JSON"})
                messages.append({"role": "tool", "tool_call_id": call.get("id") or f"call_{i}", "content": content})
        else:
            result.text = "요청을 처리하는 데 단계가 너무 많이 필요해서 멈췄어요."

        if not result.text:
            result.text = "죄송해요, 뭐라고 답해야 할지 모르겠어요."
        self.history += [turn, {"role": "assistant", "content": result.text}]
        self.history = self.history[-self.config.history_turns * 2 :]
        return result

    async def _post(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.config.openai_compat.max_tokens,
            **self.config.openai_compat.extra_body,
        }
        tools = self._tool_specs()
        if tools:
            body["tools"] = tools
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            resp = await self.client.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
        except httpx2.TimeoutException as e:
            raise LLMRetryableError(f"timeout: {e}") from e
        except httpx2.TransportError as e:
            raise LLMRetryableError(f"network: {e}") from e

        if resp.status_code == 200:
            return resp.json()
        detail = resp.text[:500]
        log.error("%s API error %s: %s", self.label, resp.status_code, detail)
        if resp.status_code == 429:
            # Free-tier quota: retrying right away only burns more of it.
            raise LLMError(detail, "무료 사용량 한도에 걸렸어요. 잠시 후에 다시 물어봐 주세요.")
        lowered = detail.lower()
        # Gemini reports key problems as 400 INVALID_ARGUMENT rather than 401.
        if resp.status_code in (401, 403) or "api key" in lowered or "authorization header" in lowered:
            raise LLMError(detail, "AI API 키를 확인해 주세요.")
        if resp.status_code == 404:
            raise LLMError(detail, "AI 모델 이름을 확인해 주세요.")
        if resp.status_code >= 500:
            raise LLMRetryableError(detail)
        raise LLMError(detail)
