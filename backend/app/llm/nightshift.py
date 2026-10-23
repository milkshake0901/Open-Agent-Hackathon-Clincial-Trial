"""app/llm/nightshift.py — Meterless Nightshift (OpenAI-compatible) provider.

To be implemented from docs/setup/meterless-provider-prompt.md (Runtime 1.4, provider contract v4):
URL normalisation, Bearer token, meterless-app / meterless-scope headers, /v1/models status,
Auto Detect. Not applied yet."""
from __future__ import annotations

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


class FakeLLM:
    """tests/fixtures/llm/<lane>/<sha256(system+user)[:16]>.json → recorded Completion. Missing fixture raises,
    so a test cannot silently hit the network. Also powers the offline demo rehearsal."""
    def __init__(self, fixtures_dir: str, record: bool = False) -> None: raise NotImplementedError
    async def complete(self, lane: Lane, system: str, user: str, out: type[T]) -> Completion[T]: raise NotImplementedError
