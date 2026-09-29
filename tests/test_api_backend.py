from types import SimpleNamespace as NS

import anthropic
import httpx2
import pytest

from helpers import ctx
from jarvis.brain.backends.api import ApiBackend
from jarvis.brain.backends.base import LLMError, LLMRetryableError
from jarvis.brain.tools import Tool, ToolRegistry, schema
from jarvis.core.config import LLMConfig


def text(t):
    return NS(type="text", text=t)


def tool_use(name, args, id_="tu_1"):
    return NS(type="tool_use", name=name, input=args, id=id_)


def response(stop, *blocks, i=50, o=10):
    return NS(stop_reason=stop, content=list(blocks), usage=NS(input_tokens=i, output_tokens=o))


class FakeClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.messages = self

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def registry():
    reg = ToolRegistry()

    async def get_status(_):
        return {"camera": "꺼짐"}

    reg.register(Tool("get_status", "상태", schema(), get_status))
    return reg


async def test_plain_answer_and_request_shape():
    client = FakeClient(response("end_turn", text("안녕하세요.")))
    backend = ApiBackend(LLMConfig(), registry(), "재원", client=client)
    result = await backend.respond("안녕", ctx())
    assert result.text == "안녕하세요." and (result.input_tokens, result.output_tokens) == (50, 10)
    req = client.requests[0]
    assert req["model"] == "claude-haiku-4-5" and req["max_tokens"] == 300
    assert req["tools"][0]["name"] == "get_status" and req["tools"][0]["strict"] is True
    assert "temperature" not in req
    assert "현재 시각: 2026-09-29 (화) 21:47 KST" in req["messages"][-1]["content"]
    assert "자비스" in req["system"]


async def test_tool_round_trip_accumulates_usage():
    client = FakeClient(
        response("tool_use", text("확인해 볼게요."), tool_use("get_status", {})),
        response("end_turn", text("카메라는 꺼져 있어요."), i=80, o=12),
    )
    backend = ApiBackend(LLMConfig(), registry(), "재원", client=client)
    result = await backend.respond("카메라 켜져 있어?", ctx())
    assert result.text == "카메라는 꺼져 있어요."
    assert (result.input_tokens, result.output_tokens) == (130, 22)
    tool_result = client.requests[1]["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result" and tool_result["tool_use_id"] == "tu_1"
    assert "꺼짐" in tool_result["content"] and tool_result["is_error"] is False


async def test_unknown_tool_is_reported_as_error_result():
    client = FakeClient(
        response("tool_use", tool_use("rm_rf", {})),
        response("end_turn", text("그건 할 수 없어요.")),
    )
    backend = ApiBackend(LLMConfig(), registry(), "재원", client=client)
    await backend.respond("다 지워", ctx())
    assert client.requests[1]["messages"][-1]["content"][0]["is_error"] is True


async def test_history_is_kept_and_trimmed():
    cfg = LLMConfig(history_turns=2)
    client = FakeClient(*[response("end_turn", text(f"답{i}")) for i in range(3)])
    backend = ApiBackend(cfg, registry(), "재원", client=client)
    for i in range(3):
        await backend.respond(f"질문{i}", ctx())
    last = client.requests[-1]["messages"]
    assert len(last) == 5  # two remembered turns + the new question
    assert last[1] == {"role": "assistant", "content": "답0"}
    assert len(backend.history) == 4
    backend.reset()
    assert backend.history == []


async def test_refusal():
    client = FakeClient(response("refusal"))
    backend = ApiBackend(LLMConfig(), registry(), "재원", client=client)
    assert "어려워요" in (await backend.respond("x", ctx())).text


def _status_error(cls, code):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx2.Response(code, request=req), body=None)


async def test_error_mapping():
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    cases = [
        (anthropic.APIConnectionError(request=req), LLMRetryableError),
        (_status_error(anthropic.RateLimitError, 429), LLMRetryableError),
        (_status_error(anthropic.InternalServerError, 500), LLMRetryableError),
        (_status_error(anthropic.AuthenticationError, 401), LLMError),
        (_status_error(anthropic.BadRequestError, 400), LLMError),
    ]
    for exc, expected in cases:
        backend = ApiBackend(LLMConfig(), registry(), "재원", client=FakeClient(exc))
        with pytest.raises(expected) as info:
            await backend.respond("x", ctx())
        if isinstance(exc, anthropic.AuthenticationError):
            assert "API 키" in info.value.user_message
            assert not isinstance(info.value, LLMRetryableError)
