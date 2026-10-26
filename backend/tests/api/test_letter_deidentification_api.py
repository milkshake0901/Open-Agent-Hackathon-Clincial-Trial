"""A letter is de-identified before it is stored, sent through Zetaris, or shown to a model (#53).

The identities are invented. Nemotron Parse is replaced on Ctx by recorded Regions; the trial model by a scripted
reply.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from app import trials
from app.config import Settings
from app.extraction import ExtractedBlock, ExtractedDocument, ExtractedPage
from app.llm.nightshift import FakeLLM
from app.main import app
from tests.conftest import ADMIN_DSN, make_ctx
from tests.fixtures.letters import (NARRATIVE_LETTER, NARRATIVE_LETTER_IDENTITY, STRUCTURED_REPORT,
                                    STRUCTURED_REPORT_IDENTITY, RecordedParse, letter_pdf)
from tests.pdfs import make_pdf

SNAPSHOT = Path(__file__).resolve().parents[3] / "data" / "trials_snapshot"
NCT = "NCT07680790"

# Everything that identifies the invented patient, in any case it is written.
IDENTIFIERS = ("Tarrant", "TARRANT", "tarrant", "Elwyn", "ELWYN", "elwyn", "P482915", "OC.4829153", "14/03/1967",
               "MP4 7QX", "Orchard Road", "Willow Lane", "Mapleton")

PAGES = (
    (1, [
        ("Page-header", "OC.4829153", (0.70, 0.02, 0.95, 0.04)),
        ("Title", "Re: TARRANT, ELWYN Age:58 Sex:M P482915(3)", (0.10, 0.10, 0.90, 0.13)),
        ("Text", "Date of birth: 14/03/1967", (0.10, 0.14, 0.50, 0.16)),
        ("Text", "Mr Tarrant was diagnosed with prostate cancer in February 2019 when his PSA was 21.",
         (0.10, 0.20, 0.90, 0.26)),
        ("Page-footer", "Example Clinic, 12 Orchard Road, Mapleton MP4 7QX", (0.10, 0.95, 0.90, 0.98)),
    ]),
    (2, [
        ("Page-header", "TARRANT, Elwyn P482915", (0.10, 0.02, 0.60, 0.04)),
        ("Text", "Since then TARRANT has received docetaxel. Elwyn remains fully active.", (0.10, 0.20, 0.90, 0.25)),
        ("Page-footer", "Willow Lane, Mapleton, Kent MP4 7QX", (0.10, 0.95, 0.90, 0.98)),
    ]),
)
FILENAME = "Elwyn_Tarrant_referral.pdf"
CONTENT = make_pdf("letter page one", "letter page two")


LETTER = ExtractedDocument(pages=tuple(
    ExtractedPage(number=n, text="\n".join(text for _, text, _ in regions),
                  blocks=tuple(ExtractedBlock(i, kind, text, *box) for i, (kind, text, box) in enumerate(regions)))
    for n, regions in PAGES))


def assert_no_identifier(text: str, identifiers: tuple[str, ...] = IDENTIFIERS) -> None:
    leaked = [i for i in identifiers if i in text]
    assert not leaked, f"{leaked} in {text!r}"


def letter_ctx(clean_db, tmp_path, recording=LETTER, llm=None):
    ctx = make_ctx(clean_db, llm, parser=RecordedParse(recording))
    return replace(ctx, settings=Settings(_env_file=None, pg_dsn=ADMIN_DSN, raw_documents_dir=str(tmp_path)))


def ask_reply(lane, system, user):
    ids = [line[1:].split("]")[0] for line in user.splitlines() if line.startswith("[") and ":p" in line.split("]")[0]]
    return {"standing": "possible", "answer": "The letter shows docetaxel.", "span_ids": ids}


async def upload(http, filename=FILENAME, content=CONTENT) -> dict:
    loaded = await http.post("/api/referrals", files={"file": (filename, content, "application/pdf")})
    assert loaded.status_code == 200, loaded.text
    return loaded.json()


async def stored_texts(pool) -> list[str]:
    spans = await pool.fetch("SELECT text FROM document_span")
    pages = await pool.fetch("SELECT text, tables_json::text AS tables FROM document_page")
    named = await pool.fetch("SELECT d.filename, p.label FROM document d JOIN patient p ON p.id = d.patient_id")
    return [*(s["text"] for s in spans), *(v for r in [*pages, *named] for v in r.values())]


@pytest.mark.parametrize("recording, identity, filename", [
    (NARRATIVE_LETTER, NARRATIVE_LETTER_IDENTITY, "Harlow_DESMOND referral.pdf"),
    (STRUCTURED_REPORT, STRUCTURED_REPORT_IDENTITY, "talia-quinn-mri.pdf"),
], ids=["narrative", "structured"])
async def test_neither_letter_fixture_stores_its_identity(clean_db, tmp_path, recording, identity, filename):
    app.state.ctx = letter_ctx(clean_db, tmp_path, recording)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        letter = await upload(http, filename, letter_pdf(recording))

    assert_no_identifier(str(letter), identity)
    for text in await stored_texts(clean_db):
        assert_no_identifier(text, identity)
    boxes = await clean_db.fetch("SELECT page, ordinal, x0, y0, x1, y1 FROM document_span ORDER BY page, ordinal")
    assert [(b["page"], b["ordinal"], (b["x0"], b["y0"], b["x1"], b["y1"])) for b in boxes] == [
        (page.number, block.ordinal, pytest.approx((block.xmin, block.ymin, block.xmax, block.ymax)))
        for page in recording.pages for block in page.blocks if block.text]


async def test_an_uploaded_letter_stores_no_name_hospital_number_or_birth_date_and_keeps_every_box(
        clean_db, tmp_path):
    app.state.ctx = letter_ctx(clean_db, tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        letter = await upload(http)
        listed = (await http.get("/api/referrals")).json()

    assert_no_identifier(str(letter))
    assert_no_identifier(str(listed))
    for text in await stored_texts(clean_db):
        assert_no_identifier(text)
    spans = await clean_db.fetch("SELECT page, ordinal, kind, text, x0, y0, x1, y1 FROM document_span "
                                 "ORDER BY page, ordinal")
    assert [(s["page"], s["ordinal"], s["kind"], (s["x0"], s["y0"], s["x1"], s["y1"])) for s in spans] == [
        (n, i, kind, pytest.approx(box)) for n, regions in PAGES for i, (kind, _, box) in enumerate(regions)]
    clinical = {s["text"] for s in spans if s["kind"] == "Text"}
    assert "[PATIENT] was diagnosed with prostate cancer in February 2019 when his PSA was 21." in clinical
    assert "Since then [PATIENT] has received docetaxel. [PATIENT] remains fully active." in clinical
    assert "Date of birth: [DOB]" in clinical


async def test_the_trial_question_shows_the_model_no_identity_and_cites_the_stored_regions(clean_db, tmp_path):
    fake = FakeLLM(ask_reply)
    ctx = letter_ctx(clean_db, tmp_path, llm=fake)
    await trials.load_snapshot(ctx, SNAPSHOT)
    app.state.ctx = ctx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        letter = await upload(http)
        asked = await http.post(f"/api/patients/{letter['patient_id']}/trials/{NCT}/ask",
                                json={"question": "Could this trial suit him after docetaxel?"})

    assert asked.status_code == 200, asked.text
    assert fake.calls
    for call in fake.calls:
        assert_no_identifier(call.system + call.user)
    stored = {r["id"]: r["text"] for r in await clean_db.fetch("SELECT id, text FROM document_span")}
    citations = asked.json()["citations"]
    assert len(citations) == 3
    assert all(c["quote"] == stored[c["span_id"]] for c in citations)
    assert_no_identifier(str(asked.json()))
