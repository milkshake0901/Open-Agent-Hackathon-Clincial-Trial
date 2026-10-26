"""Document extraction without a network call. The model is a fake."""
from __future__ import annotations

import io
import json

import pypdfium2 as pdfium
import pytest
from langchain_core.messages import AIMessage

from app.extraction import NemotronParse, extract_pdf
from app.extraction.client import MissingNvidiaKey, parse_client
from app.extraction.parse import _as_blocks, _text_from_tool_calls
from app.config import Settings


class _Fake:
    def __init__(self) -> None:
        self.messages = []

    def invoke(self, messages):
        self.messages.append(messages)
        return AIMessage(content=f"page text {len(self.messages)}", additional_kwargs={})


def _blank_pdf(pages: int) -> bytes:
    pdf = pdfium.PdfDocument.new()
    for _ in range(pages):
        pdf.new_page(612, 792)
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    return buf.getvalue()


def test_extract_pdf_asks_the_model_once_per_page():
    fake = _Fake()
    document = extract_pdf(_blank_pdf(2), client=fake)
    assert [page.number for page in document.pages] == [1, 2]
    assert document.pages[0].text == "page text 1"
    assert document.pages[1].text == "page text 2"
    content = fake.messages[0][0].content
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")


def test_tool_call_blocks_are_read_top_to_bottom():
    message = {"tool_calls": [{"function": {"arguments": json.dumps([[
        {"bbox": {"xmin": 0.1, "ymin": 0.4, "xmax": 0.2, "ymax": 0.5}, "text": "second", "type": "Text"},
        {"bbox": {"xmin": 0.1, "ymin": 0.1, "xmax": 0.2, "ymax": 0.2}, "text": "first", "type": "Title"},
    ]])}}]}
    assert _text_from_tool_calls(message) == "first\nsecond"
    blocks = _as_blocks(message)
    assert [(block.ordinal, block.kind, block.text, block.ymin) for block in blocks] == [
        (0, "Title", "first", 0.1),
        (1, "Text", "second", 0.4),
    ]
    assert blocks[0].span_id("abcdef0123456789", 2) == "abcdef012345:p2:b0"


def test_parse_client_refuses_a_missing_key():
    with pytest.raises(MissingNvidiaKey):
        parse_client(Settings(nvidia_parse_api_key=""))


def test_the_production_parser_needs_its_key_only_when_it_reads():
    parser = NemotronParse(Settings(_env_file=None, nvidia_parse_api_key=""))   # what startup builds: no error
    with pytest.raises(MissingNvidiaKey):
        parser.read(_blank_pdf(1))
