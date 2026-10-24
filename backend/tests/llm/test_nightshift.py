"""Nightshift provider contract (Runtime 1.4, provider contract v4) against a mocked runtime."""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel

from app import llm
from app.llm import Lane, LlmUnavailable
from app.llm.nightshift import Nightshift, auto_detect, normalize_base_url, parse_connect_link, strip_reasoning

TOKEN = "test-token"
MODELS = {"object": "list", "data": [{"id": "meterless/auto"}, {"id": "nvidia/nemotron-3.5-lightning-30b-a3b"}]}


def runtime(seen: list[httpx.Request], *, reply: str = "pong", model: str = "nvidia/nemotron-3.5-lightning-30b-a3b"):
    def handle(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"error": {"code": "unauthorized"}})
        if req.url.path == "/v1/models":
            return httpx.Response(200, json=MODELS)
        if req.url.path == "/v1/chat/completions":
            return httpx.Response(200, json={"id": "c1", "object": "chat.completion", "created": 0, "model": model,
                                             "choices": [{"index": 0, "finish_reason": "stop",
                                                          "message": {"role": "assistant", "content": reply}}],
                                             "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}})
        return httpx.Response(404)
    return httpx.MockTransport(handle)


def ns(seen, token=TOKEN, **kw) -> Nightshift:
    return Nightshift("127.0.0.1:8088", token, "TrialMatch", {"fast": "nvidia/nemotron-3.5-lightning-30b-a3b"},
                      transport=runtime(seen, **kw))


@pytest.mark.parametrize("pasted", [
    "127.0.0.1:8088", "http://127.0.0.1:8088", "http://127.0.0.1:8088/", "http://127.0.0.1:8088/v1",
    "http://127.0.0.1:8088/v1/", "http://127.0.0.1:8088/v1/chat/completions", "http://127.0.0.1:8088/v1/models",
    "http://127.0.0.1:8088/healthz", "http://127.0.0.1:8088/v1/v1",
])
def test_pasted_urls_normalise_to_host_v1(pasted):
    assert normalize_base_url(pasted) == "http://127.0.0.1:8088/v1"


def test_connect_link_gives_base_url_and_key():
    assert parse_connect_link("http://192.168.1.5:8090/connect#k=abc123") == ("http://192.168.1.5:8090/v1", "abc123")
    assert parse_connect_link("http://192.168.1.5:8090/v1") is None


def test_reasoning_leak_is_stripped():
    assert strip_reasoning("The user wants pong.</think>pong") == "pong"
    assert strip_reasoning("<think>hmm</think>\n pong") == "pong"


async def test_status_online_unauthorized_offline():
    seen: list[httpx.Request] = []
    state, ids = await ns(seen).status()
    assert state == "online" and "meterless/auto" in ids
    assert seen[0].headers["meterless-app"] == "trialmatch"
    assert (await ns(seen, token="rt-local").status())[0] == "unauthorized"

    down = Nightshift("127.0.0.1:1", TOKEN, "trialmatch", {}, transport=httpx.MockTransport(
        lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused"))))
    assert (await down.status())[0] == "offline"
    teapot = Nightshift("127.0.0.1:1", TOKEN, "trialmatch", {}, transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert (await teapot.status())[0] == "offline"


async def test_auto_detect_saves_the_first_hit():
    def handle(req):
        if req.url.port == 8090 and req.url.host == "localhost":
            return httpx.Response(401)
        raise httpx.ConnectError("refused")
    assert await auto_detect(TOKEN, "trialmatch", transport=httpx.MockTransport(handle)) == ("http://localhost:8090/v1", "unauthorized")


async def test_plain_text_request_returns_a_string_with_scope_header():
    seen: list[httpx.Request] = []
    assert await ns(seen, reply="Thinking.</think>pong").text("Say pong") == "pong"
    chat = seen[-1]
    body = json.loads(chat.content)
    assert body["messages"] == [{"role": "user", "content": "Say pong"}]
    assert chat.headers["meterless-scope"] == "user" and chat.headers["authorization"] == f"Bearer {TOKEN}"


async def test_wrong_token_on_chat_is_unavailable_not_a_crash():
    with pytest.raises(LlmUnavailable, match="unauthorized"):
        await ns([], token="rt-local").text("hi")


class Answer(BaseModel):
    answer: str
    confident: bool


async def test_lane_completion_goes_through_langchain_pinned_model():
    seen: list[httpx.Request] = []
    done = await ns(seen, reply='```json\n{"answer": "yes", "confident": true}\n```').complete(Lane.FAST, "sys", "q", Answer)
    assert done.value == Answer(answer="yes", confident=True)
    assert done.model_requested == done.model_answered == "nvidia/nemotron-3.5-lightning-30b-a3b"
    req = seen[-1]
    assert json.loads(req.content)["response_format"] == {"type": "json_object"}
    assert req.headers["meterless-app"] == "trialmatch" and req.headers["meterless-scope"] == "user"


async def test_gateway_retries_once_with_the_validation_error_then_gives_up():
    calls: list[str] = []

    class Flaky:
        async def complete(self, lane, system, user, out):
            calls.append(user)
            return out.model_validate_json('{"answer": 1}')   # always invalid

    with pytest.raises(LlmUnavailable, match="did not parse twice"):
        await llm.complete(SimpleNamespace(llm=Flaky()), Lane.JUDGE, system="s", user="u", out=Answer, run_id=None)
    assert len(calls) == 2 and "did not match the schema" in calls[1]
