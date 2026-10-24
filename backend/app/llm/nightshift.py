"""app/llm/nightshift.py — Meterless Nightshift (OpenAI-compatible) provider.

To be implemented from docs/setup/meterless-provider-prompt.md (Runtime 1.4, provider contract v4):
URL normalisation, Bearer token, meterless-app / meterless-scope headers, /v1/models status,
Auto Detect. Not applied yet."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.llm import Completion, Lane, T


class Nightshift:
    """openai.AsyncOpenAI(base_url=METERLESS_BASE_URL, api_key=METERLESS_RUNTIME_TOKEN,
    default_headers={"meterless-app": APP_ID, "meterless-scope": "user"}, timeout=180).
    lanes: dict[Lane, str] from Settings. response_format={"type":"json_object"} + schema in system prompt."""
    def __init__(self, base_url: str, token: str, app_id: str, lanes: dict[Lane, str]) -> None: raise NotImplementedError
    async def complete(self, lane: Lane, system: str, user: str, out: type[T]) -> Completion[T]: raise NotImplementedError
    async def models(self) -> list[str]:
        """GET /v1/models — startup check that the pinned lane models exist; warn, do not fail."""
        raise NotImplementedError


@dataclass(frozen=True)
class FakeCall:
    lane: Lane
    system: str
    user: str


class FakeLLM:
    """The test (and offline demo) model. Every prompt is captured in `.calls`, so tests can assert that no
    call was made or that a prompt never contains the postcode.

    Scripted mode (#7): `responder(lane, system, user) -> dict` returns the JSON the model would answer.
    Without a responder every call raises, so a test cannot silently reach a model.
    Planned fixture mode (#8): tests/fixtures/llm/<lane>/<sha256(system+user)[:16]>.json → recorded Completion."""
    def __init__(self, responder: Callable[[Lane, str, str], dict] | None = None) -> None:
        self.responder = responder
        self.calls: list[FakeCall] = []

    async def complete(self, lane: Lane, system: str, user: str, out: type[T]) -> Completion[T]:
        self.calls.append(FakeCall(lane, system, user))
        if self.responder is None:
            raise LookupError(f"FakeLLM has no response scripted for a {lane} call")
        return Completion(value=out.model_validate(self.responder(lane, system, user)), model_requested="fake",
                          model_answered="fake", prompt_tokens=0, completion_tokens=0, latency_ms=0)
