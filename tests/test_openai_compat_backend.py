import json

import httpx2
import pytest

from helpers import ctx
from jarvis.brain.backends.base import LLMError, LLMRetryableError
from jarvis.brain.backends.openai_compat import OpenAICompatBackend, function_schema
from jarvis.brain.tools import Tool, ToolRegistry, schema
from jarvis.core.config import LLMConfig, OpenAICompatConfig


def registry():
    reg = ToolRegistry()

    async def get_status(_):
        return {"camera": "꺼짐"}

    reg.register(Tool("get_status", "상태", schema(), get_status))
    return reg


def completion(content=None, tool_calls=None, finish="stop", p=40, c=8):
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"choices": [{"message": msg, "finish_reason": finish}], "usage": {"prompt_tokens": p, "completion_tokens": c}}


class Server:
    """Records requests and replays canned (status, json) responses."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append({"url": str(request.url), "headers": dict(request.headers), "body": json.loads(request.content)})
        status, body = self.responses.pop(0)
        return httpx2.Response(status, json=body)


def make(server, env=None, **cfg):
    config = LLMConfig(openai_compat=OpenAICompatConfig(**cfg))
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(server))
    return OpenAICompatBackend(config, registry(), "재원", client=client, env=env if env is not None else {"GEMINI_API_KEY": "g-key"})


async def test_gemini_defaults_and_request_shape():
    server = Server((200, completion("안녕하세요.")))
    backend = make(server)
    assert backend.availability() == "ok" and backend.label == "Gemini"
    result = await backend.respond("안녕", ctx())
    assert result.text == "안녕하세요." and (result.input_tokens, result.output_tokens) == (40, 8)

    req = server.requests[0]
    assert req["url"] == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert req["headers"]["authorization"] == "Bearer g-key"
    body = req["body"]
    assert body["model"] == "gemini-flash-latest" and body["max_tokens"] == 1024
    assert body["messages"][0]["role"] == "system" and "자비스" in body["messages"][0]["content"]
    fn = body["tools"][0]["function"]
    assert fn["name"] == "get_status" and "additionalProperties" not in fn["parameters"]


async def test_tool_round_trip():
    server = Server(
        (200, completion(None, [{"id": "c1", "type": "function", "function": {"name": "get_status", "arguments": "{}"}}], "tool_calls")),
        (200, completion("카메라는 꺼져 있어요.", p=60, c=9)),
    )
    backend = make(server)
    result = await backend.respond("카메라 켜져 있어?", ctx())
    assert result.text == "카메라는 꺼져 있어요." and result.input_tokens == 100
    msgs = server.requests[1]["body"]["messages"]
    assert msgs[-2]["tool_calls"][0]["id"] == "c1"
    assert msgs[-1]["role"] == "tool" and msgs[-1]["tool_call_id"] == "c1" and "꺼짐" in msgs[-1]["content"]


async def test_bad_tool_arguments_become_error_result():
    server = Server(
        (200, completion(None, [{"id": "c1", "function": {"name": "get_status", "arguments": "{oops"}}], "tool_calls")),
        (200, completion("확인하지 못했어요.")),
    )
    await make(server).respond("상태?", ctx())
    assert "not valid JSON" in server.requests[1]["body"]["messages"][-1]["content"]


async def test_history_kept():
    server = Server((200, completion("답1")), (200, completion("답2")))
    backend = make(server)
    await backend.respond("질문1", ctx())
    await backend.respond("질문2", ctx())
    msgs = server.requests[1]["body"]["messages"]
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[2]["content"] == "답1"


async def test_thinking_ran_out_of_tokens():
    server = Server((200, completion("", finish="length")))
    assert "끝내지 못했어요" in (await make(server).respond("x", ctx())).text


@pytest.mark.parametrize(
    "status,exc,phrase",
    [
        (429, LLMError, "무료 사용량"),
        (401, LLMError, "API 키"),
        (404, LLMError, "모델 이름"),
        (503, LLMRetryableError, "인터넷"),
    ],
)
async def test_error_mapping(status, exc, phrase):
    server = Server((status, {"error": {"message": "x"}}))
    with pytest.raises(exc) as info:
        await make(server).respond("x", ctx())
    assert phrase in info.value.user_message
    if status == 429:
        assert not isinstance(info.value, LLMRetryableError)  # don't burn free quota on retries


async def test_network_error_is_retryable():
    def boom(request):
        raise httpx2.ConnectError("down", request=request)

    backend = OpenAICompatBackend(
        LLMConfig(), registry(), "재원",
        client=httpx2.AsyncClient(transport=httpx2.MockTransport(boom)), env={"GEMINI_API_KEY": "k"},
    )
    with pytest.raises(LLMRetryableError):
        await backend.respond("x", ctx())


def test_problems_are_reported():
    assert "GEMINI_API_KEY" in make(Server(), env={}).problem()
    assert "model" in make(Server(), provider="groq", env={"GROQ_API_KEY": "k"}).problem()
    ollama = make(Server(), provider="ollama", model="qwen2.5:3b", env={})
    assert ollama.problem() is None and ollama.base_url == "http://127.0.0.1:11434/v1"
    custom = make(Server(), provider="custom", model="m", base_url="http://x/v1/", api_key_env="MY_KEY", env={"MY_KEY": "k"})
    assert custom.problem() is None and custom.base_url == "http://x/v1"


def test_function_schema_loosening():
    s = {"type": "object", "properties": {"a": {"type": "object", "properties": {}, "additionalProperties": False}},
         "required": [], "additionalProperties": False}
    assert function_schema(s) == {"type": "object", "properties": {"a": {"type": "object", "properties": {}}}}


def test_personal_data_hidden_for_free_tier():
    event = {"title": "UMC 스터디", "start": "2026-09-29T22:30:00+09:00"}
    assert "UMC 스터디" in ctx(next_event=event).prompt_block()
    private = ctx(next_event=event)
    private.personal = False
    block = private.prompt_block()
    assert "UMC" not in block and "22:30" in block
    cfg = LLMConfig()
    assert not cfg.personal_data_allowed("openai_compat") and cfg.personal_data_allowed("api")
    assert LLMConfig(send_personal_data=True).personal_data_allowed("openai_compat")


async def test_gemini_bad_key_is_400():
    server = Server((400, [{"error": {"code": 400, "message": "API key not valid. Please pass a valid API key."}}]))
    with pytest.raises(LLMError) as info:
        await make(server).respond("x", ctx())
    assert "API 키" in info.value.user_message
