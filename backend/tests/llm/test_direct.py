"""Lanes on NVIDIA's API (app/llm/direct.py): which provider each lane's call reaches, against mocked endpoints."""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
from pydantic import BaseModel

from app import llm
from app.config import NEMOTRON_LIGHTNING, NEMOTRON_ULTRA, Settings
from app.llm import Lane
from app.llm.direct import LaneRouter, connect
from app.llm.nightshift import Nightshift

NIGHTSHIFT_TOKEN = "nightshift-token"
NVIDIA_KEY = "nvapi-test"


class Answer(BaseModel):
    answer: str


def endpoint(seen: list[httpx.Request], token: str, model: str):
    """An OpenAI-compatible endpoint that answers as `model` to callers presenting `token`."""
    def handle(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.headers.get("authorization") != f"Bearer {token}":
            return httpx.Response(401, json={"error": {"code": "unauthorized"}})
        return httpx.Response(200, json={"id": "c1", "object": "chat.completion", "created": 0, "model": model,
                                         "choices": [{"index": 0, "finish_reason": "stop",
                                                      "message": {"role": "assistant", "content": '{"answer": "yes"}'}}],
                                         "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}})
    return httpx.MockTransport(handle)


def settings(**kw) -> Settings:
    return Settings(_env_file=None, meterless_runtime_token=NIGHTSHIFT_TOKEN,
                    lane_models={"fast": NEMOTRON_ULTRA, "deep": NEMOTRON_ULTRA, "judge": NEMOTRON_ULTRA}, **kw)


JUDGE_ON_LIGHTNING = {"judge": NEMOTRON_LIGHTNING}


def wired(**kw):
    to_nightshift: list[httpx.Request] = []
    to_nvidia: list[httpx.Request] = []
    provider = connect(settings(**kw), transport=endpoint(to_nightshift, NIGHTSHIFT_TOKEN, NEMOTRON_ULTRA),
                       direct_transport=endpoint(to_nvidia, NVIDIA_KEY, NEMOTRON_LIGHTNING))
    return provider, to_nightshift, to_nvidia


async def test_with_an_nvidia_key_the_judge_lane_reaches_lightning_on_nvidias_api():
    provider, to_nightshift, to_nvidia = wired(nvidia_api_key=NVIDIA_KEY, direct_lanes=JUDGE_ON_LIGHTNING)
    done = await llm.complete(SimpleNamespace(llm=provider), Lane.JUDGE, system="sys", user="claims", out=Answer,
                              run_id=None)
    assert done.value.answer == "yes"
    assert done.model_requested == done.model_answered == NEMOTRON_LIGHTNING
    assert to_nightshift == [] and len(to_nvidia) == 1
    req = to_nvidia[0]
    assert req.url.host == "integrate.api.nvidia.com" and req.url.path == "/v1/chat/completions"
    assert json.loads(req.content)["model"] == NEMOTRON_LIGHTNING
    assert "meterless-app" not in req.headers and "meterless-scope" not in req.headers


async def test_lanes_not_listed_as_direct_stay_on_nightshift():
    provider, to_nightshift, to_nvidia = wired(nvidia_api_key=NVIDIA_KEY, direct_lanes=JUDGE_ON_LIGHTNING)
    for lane in (Lane.FAST, Lane.DEEP):
        done = await llm.complete(SimpleNamespace(llm=provider), lane, system="sys", user="q", out=Answer, run_id=None)
        assert done.model_requested == done.model_answered == NEMOTRON_ULTRA
    assert to_nvidia == [] and len(to_nightshift) == 2
    assert all(r.headers["meterless-app"] == "trialmatch" for r in to_nightshift)


async def test_without_an_nvidia_key_every_lane_stays_on_nightshift():
    provider, to_nightshift, to_nvidia = wired(direct_lanes=JUDGE_ON_LIGHTNING)
    assert isinstance(provider, Nightshift) and not isinstance(provider, LaneRouter)
    done = await llm.complete(SimpleNamespace(llm=provider), Lane.JUDGE, system="sys", user="claims", out=Answer,
                              run_id=None)
    assert done.model_requested == NEMOTRON_ULTRA
    assert to_nvidia == [] and len(to_nightshift) == 1


async def test_by_default_every_lane_stays_on_nightshift_even_with_a_key():
    provider, _, _ = wired(nvidia_api_key=NVIDIA_KEY)
    assert not isinstance(provider, LaneRouter)
    assert provider.model_for(Lane.JUDGE) == NEMOTRON_ULTRA


async def test_model_for_names_the_model_of_the_provider_that_serves_the_lane():
    provider, _, _ = wired(nvidia_api_key=NVIDIA_KEY, direct_lanes=JUDGE_ON_LIGHTNING)
    assert provider.model_for(Lane.JUDGE) == NEMOTRON_LIGHTNING
    assert provider.model_for(Lane.DEEP) == NEMOTRON_ULTRA
    assert provider.model_for(None) == provider.nightshift.default_model
