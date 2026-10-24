"""Media on a Meterless job: plan from discovery, source job, attempt, materialize, make, artifact bytes.
The fake runtime behaves like Runtime 1.4 where the real one is uncooperative: the attempts list is not
served (501), the winner isn't seq 1, the parent job completes before the make, and artifacts need the bearer."""
from __future__ import annotations

import json

import httpx
import pytest

from app.llm import Media, MediaFailed, MediaUnavailable
from app.llm.nightshift import Nightshift

TOKEN = "test-token"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

CLASSES = {"object": "class_index", "classes": {
    "image": {"class": "image", "chat_carrier": False, "why": "no image lane"},
    "speech": {"class": "speech", "chat_carrier": None, "why": "no voice-tts engine"},
    "music": {"class": "music", "why": "no music-ace engine"},
}}


def transforms(**available) -> dict:
    t = [
        {"id": "artifact.image.edit", "kind": "image", "capability": "media.image_edit", "available": True},
        {"id": "attempt.image.alt", "kind": "image", "capability": "media.image_still", "available": True},
        {"id": "attempt.image.still", "kind": "image", "capability": "media.image_still",
         "available": available.get("still", True), "reason": "no healthy artifact engine offers media.image_still"},
        {"id": "attempt.image.internal", "kind": "image", "pipeline": "still", "internal": True, "available": True},
        {"id": "attempt.voice.text", "kind": "text", "capability": "media.voice_narrate", "available": True},
        {"id": "attempt.voice.narrate", "kind": "audio", "capability": "media.voice_narrate",
         "available": available.get("narrate", False), "reason": "no voice engine under the local-only floor"},
    ]
    return {"object": "list", "data": t}


class FakeRuntime:
    def __init__(self, *, still=True, materialize_error=None, artifact_mime="image/png"):
        self.still, self.materialize_error, self.artifact_mime = still, materialize_error, artifact_mime
        self.requests: list[httpx.Request] = []
        self.make_polls = 0
        self.job_polls = 0

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        if req.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"error": {"code": "unauthorized"}})
        p, m = req.url.path, req.method
        if p == "/v1/meterless/classes":
            return httpx.Response(200, json=CLASSES)
        if p == "/v1/meterless/transforms":
            return httpx.Response(200, json=transforms(still=self.still))
        if p == "/v1/jobs" and m == "POST":
            return httpx.Response(200, json={"id": "job_1", "status": "queued"})
        if p == "/v1/jobs/job_1":
            self.job_polls += 1
            generated = 0 if self.job_polls < 2 else 2
            return httpx.Response(200, json={"id": "job_1", "status": "completed" if generated else "running",
                                             "generated": generated, "winner_seq": 2 if generated else None})
        if p == "/v1/jobs/job_1/attempts":
            return httpx.Response(501, json={"error": {"code": "route_not_implemented"}})
        if p == "/v1/jobs/job_1/attempts/1":
            return httpx.Response(200, json={"seq": 1, "text": "", "error": "lane crashed"})
        if p == "/v1/jobs/job_1/attempts/2":
            return httpx.Response(200, json={"seq": 2, "text": "A calm garden.", "error": None})
        if p == "/v1/jobs/job_1/materialize":
            if self.materialize_error:
                return httpx.Response(409 if self.materialize_error["code"] == "already_made" else 400,
                                      json={"error": self.materialize_error})
            return httpx.Response(200, json={"make_ids": ["mk_7"]})
        if p == "/v1/jobs/job_1/makes":
            self.make_polls += 1
            status = "running" if self.make_polls < 3 else "done"
            return httpx.Response(200, json={"object": "list", "data": [
                {"id": "mk_other", "status": "done", "outputs": ["nope.png"]},
                {"id": "mk_7", "status": status, "outputs": ["still.json", "still.png"]}]})
        if p == "/v1/jobs/job_1/attempts/2/artifacts":
            return httpx.Response(200, json={"data": [
                {"name": "still.json", "mime": "application/json", "url": "/v1/jobs/job_1/attempts/2/artifacts/still.json"},
                {"name": "prompt.txt", "mime": "text/plain"},
                {"name": "still.png", "mime": "image/png", "size": len(PNG),
                 "url": "/v1/jobs/job_1/attempts/2/artifacts/still.png"}]})
        if p == "/v1/jobs/job_1/attempts/2/artifacts/still.png":
            return httpx.Response(200, content=PNG, headers={"content-type": self.artifact_mime})
        return httpx.Response(404, json={"error": {"code": "not_found", "path": p}})

    def bodies(self, path: str) -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.url.path == path and r.method == "POST"]


def media(rt: FakeRuntime, tmp_path, clock=None) -> Media:
    ns = Nightshift("http://127.0.0.1:8088/v1", TOKEN, "trialmatch", {}, transport=httpx.MockTransport(rt))
    return Media(ns, tmp_path, poll_s=0, wait_s=30, **({"clock": clock} if clock else {}))


async def test_plan_prefers_the_named_transform_and_skips_internal_and_unavailable(tmp_path):
    m = media(FakeRuntime(), tmp_path)
    assert (await m.plan("image")).target == "attempt.image.still"
    m2 = media(FakeRuntime(still=False), tmp_path)
    assert (await m2.plan("image")).target == "attempt.image.alt"


async def test_a_text_transform_never_satisfies_speech(tmp_path):
    with pytest.raises(MediaUnavailable) as e:
        await media(FakeRuntime(), tmp_path).plan("speech")
    assert str(e.value) == "Speech unavailable: no voice engine under the local-only floor"


async def test_no_match_falls_back_to_the_class_reason(tmp_path):
    with pytest.raises(MediaUnavailable, match="^Music unavailable: no music-ace engine$"):
        await media(FakeRuntime(), tmp_path).plan("music")


async def test_chat_carrier_wins_over_transforms(tmp_path, monkeypatch):
    monkeypatch.setitem(CLASSES["classes"]["image"], "chat_carrier", True)
    plan = await media(FakeRuntime(), tmp_path).plan("image")
    assert (plan.via, plan.target) == ("chat", "image")


async def test_discovery_is_cached_for_60_seconds(tmp_path):
    now = [0.0]
    rt = FakeRuntime()
    m = media(rt, tmp_path, clock=lambda: now[0])
    await m.plan("image"); now[0] = 59; await m.plan("image")
    assert sum(r.url.path == "/v1/meterless/classes" for r in rt.requests) == 1
    now[0] = 61; await m.plan("image")
    assert sum(r.url.path == "/v1/meterless/classes" for r in rt.requests) == 2


async def test_illustrate_makes_a_real_image_and_stores_it(tmp_path):
    rt = FakeRuntime()
    made = await media(rt, tmp_path).illustrate("A calm watercolour of a hospital garden", privacy="local-only")

    assert made.path.read_bytes() == PNG and made.mime == "image/png" and made.size == len(PNG)
    assert (made.job_id, made.seq, made.make_id, made.transform) == ("job_1", 2, "mk_7", "attempt.image.still")
    assert made.path.is_relative_to(tmp_path)

    [job] = rt.bodies("/v1/jobs")
    assert job == {"kind": "best_of_n", "app": "trialmatch", "mode": "meterless/text", "n": 1, "window": "now",
                   "privacy": "local-only", "media_autopilot": {"mode": "off"},
                   "messages": [{"role": "user", "content": "A calm watercolour of a hospital garden"}]}
    [mat] = rt.bodies("/v1/jobs/job_1/materialize")
    assert mat == {"seq": 2, "transform": "attempt.image.still", "n": 1, "window": "now",
                   "media_controls": {"text": "A calm watercolour of a hospital garden"}}
    assert rt.make_polls == 3, "waits on the make's own status, not the completed parent job"
    assert all(r.headers["authorization"] == f"Bearer {TOKEN}" for r in rt.requests)


async def test_privacy_floor_is_sent_as_given_and_validated(tmp_path):
    rt = FakeRuntime()
    await media(rt, tmp_path).illustrate("x", privacy="edge-only")
    assert rt.bodies("/v1/jobs")[0]["privacy"] == "edge-only"
    with pytest.raises(ValueError):
        await media(FakeRuntime(), tmp_path).illustrate("x", privacy="anywhere")


async def test_already_made_with_a_make_id_counts_as_success(tmp_path):
    rt = FakeRuntime(materialize_error={"code": "already_made", "make_id": "mk_7"})
    assert (await media(rt, tmp_path).illustrate("x", privacy="local-only")).make_id == "mk_7"


async def test_runtime_without_a_media_engine_is_unavailable(tmp_path):
    rt = FakeRuntime(materialize_error={"code": "runtime_unavailable", "message": "runtime_unavailable: no sd-server"})
    with pytest.raises(MediaUnavailable, match="^Images unavailable: runtime_unavailable: no sd-server$"):
        await media(rt, tmp_path).illustrate("x", privacy="local-only")


async def test_wrong_content_type_is_rejected(tmp_path):
    with pytest.raises(MediaFailed, match="text/html"):
        await media(FakeRuntime(artifact_mime="text/html"), tmp_path).illustrate("x", privacy="local-only")
    assert not list(tmp_path.rglob("*.png"))
