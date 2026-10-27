"""Every uploaded PDF is read into Regions (#45): the documents upload reads through the Parser on Ctx,
de-identifies the whole Document, and stores its pages and Regions with their boxes.

Nemotron Parse is replaced on Ctx by recorded Regions (tests/fixtures/letters.py); the Intake model by a scripted
reply. Every identity is invented.
"""
from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from app.config import Settings
from app.llm.nightshift import FakeLLM
from app.main import app
from tests.conftest import ADMIN_DSN, make_ctx
from tests.review import use_all_as_read
from tests.fixtures.letters import (NARRATIVE_LETTER, NARRATIVE_LETTER_IDENTITY, STRUCTURED_REPORT,
                                    STRUCTURED_REPORT_IDENTITY, RecordedParse, intake_reading, letter_pdf,
                                    recording)


def no_facts(lane, system, user):
    return {"facts": []}


ACL_TEAR = [{"resource": "Condition", "subject": "anterior cruciate ligament tear", "value": "complete",
             "observed_on": "2026-10-02", "quote": "complete tear of the proximal fibres"}]
acl_tear = intake_reading(ACL_TEAR)


def documents_ctx(clean_db, tmp_path, parser, intake=no_facts):
    ctx = make_ctx(clean_db, FakeLLM(intake), parser=parser)
    return replace(ctx, settings=Settings(_env_file=None, pg_dsn=ADMIN_DSN, raw_documents_dir=str(tmp_path)))


async def new_patient(http) -> str:
    return (await http.post("/api/patients", json={"label": "Demo patient R"})).json()["patient_id"]


def assert_no_identifier(text: str, identifiers: tuple[str, ...]) -> None:
    leaked = [i for i in identifiers if i in text]
    assert not leaked, f"{leaked} in {text!r}"


def recorded_boxes(document):
    return [(page.number, block.ordinal, block.kind, pytest.approx((block.xmin, block.ymin, block.xmax, block.ymax)))
            for page in document.pages for block in page.blocks if block.text]


@pytest.mark.parametrize("document, identity", [
    (STRUCTURED_REPORT, STRUCTURED_REPORT_IDENTITY),
    (NARRATIVE_LETTER, NARRATIVE_LETTER_IDENTITY),
], ids=["structured", "narrative"])
async def test_an_added_document_is_stored_as_deidentified_regions_with_their_boxes(
        clean_db, tmp_path, document, identity):
    parser = RecordedParse(document)
    app.state.ctx = documents_ctx(clean_db, tmp_path, parser)
    content = letter_pdf(document)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        patient = await new_patient(http)
        added = await http.post(f"/api/patients/{patient}/documents",
                                files={"file": ("report.pdf", content, "application/pdf")})
        assert added.status_code == 202, added.text
        regions = await http.get(f"/api/documents/{added.json()['document_hash']}/regions")

    assert parser.reads == [content]
    assert regions.status_code == 200
    body = regions.json()
    assert body["page_count"] == len(document.pages)
    assert [(r["page"], r["ordinal"], r["kind"], (r["x0"], r["y0"], r["x1"], r["y1"]))
            for r in body["regions"]] == recorded_boxes(document)
    assert all(r["span_id"].startswith(f"{added.json()['document_hash'][:12]}:p{r['page']}:b") for r in body["regions"])
    assert_no_identifier(str(body), identity)


async def test_adding_the_same_document_again_answers_with_the_same_run_and_reads_it_once(clean_db, tmp_path):
    parser = RecordedParse(STRUCTURED_REPORT)
    app.state.ctx = documents_ctx(clean_db, tmp_path, parser, intake=acl_tear)
    content = letter_pdf(STRUCTURED_REPORT)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        patient = await new_patient(http)
        first = await http.post(f"/api/patients/{patient}/documents", files={"file": ("mri.pdf", content)})
        again = await http.post(f"/api/patients/{patient}/documents", files={"file": ("mri (1).pdf", content)})
        run = await use_all_as_read(http, first.json()["run_id"])
        regions = (await http.get(f"/api/documents/{first.json()['document_hash']}/regions")).json()

    assert run["state"]["phase"] == "committed"
    assert again.json() == {**first.json(), "deduplicated": True}
    assert parser.reads == [content]
    assert len(regions["regions"]) == len(recorded_boxes(STRUCTURED_REPORT))


BLANK = recording("")
"""A parse that finds nothing on the page: a blank page, or a scan too faint to read."""
LETTERHEAD_ONLY = recording((("Page-header", "Lakeshore Imaging"), ("Page-footer", "7 Pier Street, Port Calder 3999")))
"""A parse that finds only a page's letterhead and footer."""


@pytest.mark.parametrize("found", [BLANK, LETTERHEAD_ONLY], ids=["blank", "letterhead-only"])
async def test_a_pdf_whose_parse_finds_no_readable_text_is_refused_and_nothing_is_stored(
        clean_db, tmp_path, found):
    app.state.ctx = documents_ctx(clean_db, tmp_path, RecordedParse(found))
    content = letter_pdf(found)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        patient = await new_patient(http)
        added = await http.post(f"/api/patients/{patient}/documents", files={"file": ("scan.pdf", content)})
        run = await http.get(f"/api/runs/{added.json()['run_id']}")

    assert added.status_code == 202
    assert run.json()["state"]["phase"] == "rejected"
    assert "no readable text" in run.json()["state"]["reason"]
    assert await clean_db.fetch("SELECT hash FROM document") == []


async def test_a_file_that_is_not_a_pdf_is_refused_without_being_read(clean_db, tmp_path):
    parser = RecordedParse(STRUCTURED_REPORT)
    app.state.ctx = documents_ctx(clean_db, tmp_path, parser)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        patient = await new_patient(http)
        added = await http.post(f"/api/patients/{patient}/documents", files={"file": ("a.pdf", b"GIF89a not a pdf")})

    assert added.status_code == 422
    assert parser.reads == []
