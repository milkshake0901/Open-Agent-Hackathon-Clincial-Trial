"""One Nemotron Parse call per page. The model reads the image and returns the page text."""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Protocol

from langchain_core.messages import HumanMessage

from app.config import Settings
from app.extraction.client import parse_client
from app.extraction.pages import render_pages

# nemotron-parse accepts an image and refuses a text prompt. The model owns the extraction.


@dataclass(frozen=True)
class ExtractedBlock:
    """One region the parse model read. Coordinates are fractions of the page, origin at the top left."""
    ordinal: int
    kind: str
    text: str
    xmin: float
    ymin: float
    xmax: float
    ymax: float

    def span_id(self, document_hash: str, page: int) -> str:
        return f"{document_hash[:12]}:p{page}:b{self.ordinal}"


@dataclass(frozen=True)
class ExtractedPage:
    number: int  # 1-based
    text: str
    reasoning: str = ""
    blocks: tuple[ExtractedBlock, ...] = ()


@dataclass(frozen=True)
class ExtractedDocument:
    pages: tuple[ExtractedPage, ...]

    @property
    def text(self) -> str:
        return "\n\n".join(f"# Page {page.number}\n{page.text}" for page in self.pages)


def _text_of(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text") or "")
        return "\n".join(parts).strip()
    return str(content).strip()


def _blocks(arguments) -> list[dict]:
    """markdown_bbox arguments are a JSON list of {bbox, text, type}, sometimes nested once."""
    parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
    while isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], list):
        parsed = parsed[0]
    return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def _layout_blocks(message: dict) -> list[dict]:
    found: list[dict] = []
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        found.extend(_blocks(function.get("arguments") or "[]"))
    found.sort(key=lambda block: (block.get("bbox", {}).get("ymin", 0), block.get("bbox", {}).get("xmin", 0)))
    return found


def _text_from_tool_calls(message: dict) -> str:
    return "\n".join(block["text"] for block in _layout_blocks(message) if block.get("text")).strip()


def _as_blocks(message: dict) -> tuple[ExtractedBlock, ...]:
    blocks: list[ExtractedBlock] = []
    for ordinal, block in enumerate(_layout_blocks(message)):
        text = (block.get("text") or "").strip()
        if not text:
            continue
        box = block.get("bbox") or {}
        blocks.append(ExtractedBlock(
            ordinal=ordinal, kind=str(block.get("type") or "Text"), text=text,
            xmin=float(box.get("xmin") or 0), ymin=float(box.get("ymin") or 0),
            xmax=float(box.get("xmax") or 0), ymax=float(box.get("ymax") or 0),
        ))
    return tuple(blocks)


def _read_with_nvidia(client, lc_messages) -> tuple[str, str, tuple[ExtractedBlock, ...]]:
    """ChatNVIDIA.invoke cannot build an AIMessage from this model's tool call, whose arguments
    are a list of layout blocks rather than a dict. The client still prepares and sends the request."""
    _, payload, extra_headers = client._prepare_inputs_and_payload(lc_messages, None, stream=False)
    response = client._client.get_req(payload=payload, extra_headers=extra_headers)
    message = response.json()["choices"][0]["message"]
    blocks = _as_blocks(message)
    text = _text_of(message.get("content")) if message.get("content") else _text_from_tool_calls(message)
    return text, message.get("reasoning_content") or "", blocks


def _read_page(client, png: bytes) -> tuple[str, str, tuple[ExtractedBlock, ...]]:
    encoded = base64.b64encode(png).decode()
    lc_messages = [HumanMessage(content=[
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
    ])]
    if hasattr(client, "_prepare_inputs_and_payload"):
        return _read_with_nvidia(client, lc_messages)
    response = client.invoke(lc_messages)
    extra = response.additional_kwargs or {}
    reasoning = extra.get("reasoning_content") or ""
    return _text_of(response.content), reasoning, ()


def extract_pdf(content: bytes, *, client=None) -> ExtractedDocument:
    """Render every page and ask Nemotron Parse to read it. `client` is injectable for tests."""
    model = client or parse_client()
    pages = tuple(
        ExtractedPage(number=n, text=text, reasoning=reasoning, blocks=blocks)
        for n, png in enumerate(render_pages(content), 1)
        for text, reasoning, blocks in [_read_page(model, png)]
    )
    return ExtractedDocument(pages=pages)


class Parser(Protocol):
    """What Ctx carries to read a PDF into pages of Regions. Tests replace it with recorded Regions."""

    def read(self, content: bytes) -> ExtractedDocument: ...


class NemotronParse:
    """The production Parser: Nemotron Parse, one call per page. The client is built on the first read,
    so a missing NVIDIA_PARSE_API_KEY fails that read (MissingNvidiaKey), never startup."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = None

    def read(self, content: bytes) -> ExtractedDocument:
        if self._client is None:
            self._client = parse_client(self._settings)
        return extract_pdf(content, client=self._client)
