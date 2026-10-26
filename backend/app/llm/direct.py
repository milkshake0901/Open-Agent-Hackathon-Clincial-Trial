"""app/llm/direct.py — lanes served by NVIDIA's own API instead of Nightshift.

Nightshift stays the provider for every lane it can serve. A lane in Settings.direct_lanes goes straight to NVIDIA's
OpenAI-compatible API (integrate.api.nvidia.com) while Nightshift can't serve its model: Lightning is switched off in
this box's Compute sources, and the judge lane needs it so a second model checks the Matcher. Only with
NVIDIA_API_KEY set; without it every lane stays on Nightshift, as before.

`connect(settings)` is how the app and scripts get their LLM: a Nightshift, or a LaneRouter over Nightshift and
NvidiaDirect. Agents never see which: they call app.llm.complete with a lane."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx

from app.llm import Lane, Reply, T
from app.llm.nightshift import TIMEOUT_S, Nightshift

if TYPE_CHECKING:
    from langchain_openai import ChatOpenAI

    from app.config import Settings

log = logging.getLogger(__name__)

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"


class NvidiaDirect(Nightshift):
    """NVIDIA's API for the lanes it is given. Same OpenAI-compatible calls and reply handling as Nightshift, with the
    NVIDIA API key and without the meterless-* headers. Serves no plain-text or media calls."""

    def __init__(self, api_key: str, lanes: dict[Lane, str], *, base_url: str = NVIDIA_BASE_URL,
                 transport: httpx.AsyncBaseTransport | None = None, timeout: float = TIMEOUT_S) -> None:
        super().__init__(base_url, api_key, "", lanes, transport=transport, timeout=timeout)

    def __repr__(self) -> str:
        return f"NvidiaDirect({self.base_url!r}, lanes={sorted(self.lanes)})"

    def chat_model(self, lane: Lane | None = None, **kwargs) -> "ChatOpenAI":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=self.model_for(lane), base_url=self.base_url, api_key=self._token or "missing",
            timeout=self._timeout, max_retries=0,
            http_async_client=httpx.AsyncClient(transport=self._transport, timeout=self._timeout) if self._transport else None,
            **kwargs,
        )


class LaneRouter:
    """Sends each lane to its provider: the direct provider's lanes to it, every other call to Nightshift. Anything
    that is not a lane call (status, models, plain text, media) is Nightshift's."""

    def __init__(self, nightshift: Nightshift, direct: NvidiaDirect) -> None:
        self.nightshift = nightshift
        self.direct = direct

    def __repr__(self) -> str:
        return f"LaneRouter({self.nightshift!r}, {self.direct!r})"

    def _for(self, lane: Lane | None) -> Nightshift:
        return self.direct if lane in self.direct.lanes else self.nightshift

    async def complete(self, lane: Lane, system: str, user: str, out: type[T]) -> Reply:
        return await self._for(lane).complete(lane, system, user, out)

    def model_for(self, lane: Lane | None) -> str:
        return self._for(lane).model_for(lane)

    def chat_model(self, lane: Lane | None = None, **kwargs) -> "ChatOpenAI":
        return self._for(lane).chat_model(lane, **kwargs)

    async def aclose(self) -> None:
        await self.direct.aclose()
        await self.nightshift.aclose()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.nightshift, name)


def connect(settings: "Settings", *, transport: httpx.AsyncBaseTransport | None = None,
            direct_transport: httpx.AsyncBaseTransport | None = None) -> Nightshift | LaneRouter:
    """The app's LLM: Nightshift for every lane, or a LaneRouter that sends Settings.direct_lanes to NVIDIA's API
    when NVIDIA_API_KEY is set. The transports are for tests."""
    nightshift = Nightshift(settings.meterless_base_url, settings.meterless_runtime_token, settings.meterless_app_id,
                            settings.lane_models, default_model=settings.meterless_model, transport=transport)
    if not settings.nvidia_api_key or not settings.direct_lanes:
        return nightshift
    direct = NvidiaDirect(settings.nvidia_api_key, {Lane(k): v for k, v in settings.direct_lanes.items()},
                          base_url=settings.nvidia_base_url, transport=direct_transport)
    for lane, model in sorted(direct.lanes.items()):
        log.info("lane %s → NVIDIA API (%s), not Nightshift", lane, model)
    return LaneRouter(nightshift, direct)
