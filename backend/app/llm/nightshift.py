"""app/llm/nightshift.py — Meterless Nightshift (OpenAI-compatible) provider.

Implements docs/setup/meterless-provider-prompt.md (Runtime 1.4, provider contract v4): URL normalisation,
Bearer token, meterless-app / meterless-scope headers, /v1/models status, Auto Detect, connect links.

Agents are built with LangChain: `chat_model(lane)` is a ChatOpenAI pointed at Nightshift with the
required headers, so an agent never configures the provider itself. Discovery, status and media jobs use
the same token over httpx. Media (image, speech, music, video) is made on a job, not chat: app/llm/media.py."""
from __future__ import annotations

import json
from dataclasses import dataclass
import logging
import re
import time
from typing import TYPE_CHECKING, Callable, Literal
from urllib.parse import parse_qs, urlsplit

import httpx

from pydantic import ValidationError

from app.llm import Completion, Lane, LlmUnavailable, T, UnparsedReply

if TYPE_CHECKING:
    from langchain_openai import ChatOpenAI

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://127.0.0.1:8088/v1"
DETECT_PORTS = (8088, 8090, 8787, 11434)
DETECT_HOSTS = ("127.0.0.1", "localhost", "[::1]")
TIMEOUT_S = 180.0          # a model load can take minutes

Status = Literal["online", "unauthorized", "offline"]


def normalize_base_url(url: str) -> str:
    """Pasted URL with or without scheme, /v1, /v1/chat/completions, /v1/models or /healthz → <host>/v1.
    Never /v1/v1."""
    u = url.strip() or DEFAULT_BASE_URL
    if "://" not in u:
        u = "http://" + u
    parts = urlsplit(u)
    path = parts.path.rstrip("/")
    for suffix in ("/chat/completions", "/models", "/healthz"):
        if path.endswith(suffix):
            path = path[: -len(suffix)].rstrip("/")
            break
    while path.endswith("/v1"):
        path = path[:-3].rstrip("/")
    return f"{parts.scheme}://{parts.netloc}{path}/v1"


def parse_connect_link(link: str) -> tuple[str, str] | None:
    """http://<host>:<port>/connect#k=<key> → (origin + /v1, key). Never log the result."""
    parts = urlsplit(link.strip())
    if not parts.scheme or not parts.path.rstrip("/").endswith("/connect"):
        return None
    key = parse_qs(parts.fragment).get("k", [""])[0]
    return (f"{parts.scheme}://{parts.netloc}/v1", key) if key else None


def strip_reasoning(text: str) -> str:
    """Some lanes leak their reasoning, sometimes without the opening tag: keep what follows the last </think>."""
    return text.rsplit("</think>", 1)[-1].strip()


def json_object(text: str) -> str:
    """The JSON object in a reply, without reasoning or code fences."""
    text = strip_reasoning(text)
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else text


class Nightshift:
    """One runtime connection. lanes: dict[Lane, str] from Settings.lane_models; default_model serves
    plain text calls. The token is sent on every request and never logged or repr'd."""

    def __init__(self, base_url: str, token: str, app_id: str, lanes: dict[Lane, str], *,
                 default_model: str = "meterless/auto", transport: httpx.AsyncBaseTransport | None = None,
                 timeout: float = TIMEOUT_S) -> None:
        self.base_url = normalize_base_url(base_url)
        self.app_id = app_id.strip().lower()
        self.lanes = {Lane(k): v for k, v in lanes.items()}
        self.default_model = default_model
        self._token = token.strip()
        self._timeout = timeout
        self._transport = transport
        self.http = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self._token}", "meterless-app": self.app_id},
            timeout=timeout, transport=transport,
        )

    def __repr__(self) -> str:
        return f"Nightshift({self.base_url!r}, app={self.app_id!r})"

    async def aclose(self) -> None:
        await self.http.aclose()

    @property
    def origin(self) -> str:
        p = urlsplit(self.base_url)
        return f"{p.scheme}://{p.netloc}"

    def model_for(self, lane: Lane | None) -> str:
        return self.lanes.get(lane, self.default_model) if lane else self.default_model

    # ---- LangChain: how agents get a model ------------------------------------------------------
    def chat_model(self, lane: Lane | None = None, **kwargs) -> "ChatOpenAI":
        """ChatOpenAI on this runtime, pinned to the lane's model. Use it to build agents and chains."""
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=self.model_for(lane), base_url=self.base_url, api_key=self._token or "missing",
            default_headers={"meterless-app": self.app_id, "meterless-scope": "user"},
            timeout=self._timeout, max_retries=0,
            http_async_client=httpx.AsyncClient(transport=self._transport, timeout=self._timeout) if self._transport else None,
            **kwargs,
        )

    # ---- status -------------------------------------------------------------------------------
    async def status(self, *, timeout: float | None = None) -> tuple[Status, list[str]]:
        """GET /v1/models decides (/healthz only proves the process is up): 401/403 → unauthorized,
        200 with meterless ids → online, anything else → offline."""
        try:
            r = await self.http.get("/models", timeout=timeout or self._timeout)
        except httpx.HTTPError:
            return "offline", []
        if r.status_code in (401, 403):
            return "unauthorized", []
        if r.status_code != 200:
            return "offline", []
        try:
            ids = [m["id"] for m in r.json().get("data", []) if isinstance(m, dict) and "id" in m]
        except ValueError:
            return "offline", []
        return ("online", ids) if any(i.startswith("meterless/") for i in ids) else ("offline", ids)

    async def models(self) -> list[str]:
        """GET /v1/models — startup check that the pinned lane models exist; warn, do not fail.
        Every id is kept, including meterless/* ids this client doesn't recognise."""
        state, ids = await self.status()
        if state != "online":
            log.warning("Nightshift at %s is %s", self.base_url, state)
            return ids
        for lane, model in self.lanes.items():
            if model not in ids:
                log.warning("lane %s is pinned to %s, which Nightshift doesn't list", lane, model)
        return ids

    # ---- chat ---------------------------------------------------------------------------------
    async def chat(self, model: str, messages: list[dict], **extra) -> dict:
        """Raw POST /v1/chat/completions. Raises LlmUnavailable on transport errors and non-2xx."""
        try:
            r = await self.http.post("/chat/completions", headers={"meterless-scope": "user"},
                                     json={"model": model, "messages": messages, **extra})
        except httpx.HTTPError as e:
            raise LlmUnavailable(f"Nightshift unreachable: {type(e).__name__}") from e
        if r.status_code in (401, 403):
            raise LlmUnavailable("Nightshift rejected the runtime token (unauthorized)")
        if not r.is_success:
            raise LlmUnavailable(f"Nightshift answered {r.status_code}: {r.text[:300]}")
        return r.json()

    async def text(self, prompt: str, *, model: str | None = None, system: str | None = None) -> str:
        """A plain text request: the prompt stays a string, exactly like OpenAI."""
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        body = await self.chat(model or self.default_model, messages)
        return strip_reasoning(body["choices"][0]["message"].get("content") or "")

    async def complete(self, lane: Lane, system: str, user: str, out: type[T]) -> Completion[T]:
        """JSON-mode call through the lane's LangChain model, parsed into `out`. A reply that doesn't
        parse raises UnparsedReply (the ValidationError and the reply text); app.llm.complete owns the one retry."""
        from langchain_core.messages import HumanMessage, SystemMessage

        model = self.model_for(lane)
        schema = json.dumps(out.model_json_schema())
        prompt = [SystemMessage(f"{system}\n\nReply with one JSON object only, matching this JSON Schema:\n{schema}"),
                  HumanMessage(user)]
        started = time.monotonic()
        try:
            msg = await self.chat_model(lane).ainvoke(prompt, response_format={"type": "json_object"})
        except Exception as e:   # openai.* errors surface through LangChain
            raise LlmUnavailable(f"{lane} lane ({model}) failed: {type(e).__name__}: {str(e)[:200]}") from e
        latency_ms = int((time.monotonic() - started) * 1000)
        raw = msg.content if isinstance(msg.content, str) else ""
        try:
            value = out.model_validate_json(json_object(raw))
        except ValidationError as e:
            raise UnparsedReply(raw, e) from e
        usage = msg.usage_metadata or {}
        return Completion(
            value=value, model_requested=model,
            model_answered=msg.response_metadata.get("model_name") or model,
            prompt_tokens=usage.get("input_tokens", 0), completion_tokens=usage.get("output_tokens", 0),
            latency_ms=latency_ms, raw=raw,
        )


async def auto_detect(token: str, app_id: str, *, transport: httpx.AsyncBaseTransport | None = None) -> tuple[str, Status] | None:
    """Try ports 8088, 8090, 8787, 11434 on 127.0.0.1, localhost and [::1]; the first online or
    unauthorized hit wins. The caller saves the URL (METERLESS_BASE_URL)."""
    for port in DETECT_PORTS:
        for host in DETECT_HOSTS:
            ns = Nightshift(f"http://{host}:{port}/v1", token, app_id, {}, transport=transport)
            try:
                state, _ = await ns.status(timeout=3.0)
            finally:
                await ns.aclose()
            if state != "offline":
                return ns.base_url, state
    return None


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
        answer = self.responder(lane, system, user)
        raw = json.dumps(answer, default=str)
        try:
            value = out.model_validate(answer)
        except ValidationError as e:
            raise UnparsedReply(raw, e) from e
        return Completion(value=value, model_requested="fake", model_answered="fake", prompt_tokens=0,
                          completion_tokens=0, latency_ms=0, raw=raw)
