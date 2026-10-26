"""Dates follow the Document, and code catches the model's misreads (#47), through the HTTP API.

The two letter fixtures (tests/fixtures/letters.py) are added to a Respondent's own patient; Intake is a scripted
model that quotes their Regions. The narrative letter writes dates day first; the structured report writes them out
and says "4 months ago". Nemotron Parse replays recorded, invented Regions; no network call is made.
"""
from __future__ import annotations

from dataclasses import replace

import httpx

from app.config import Settings
from app.llm.nightshift import FakeLLM
from app.main import app
from tests.api.test_letter_citations_api import LETTER_FACTS, add_letter, letter_ctx
from tests.conftest import ADMIN_DSN, make_ctx
from tests.fixtures.letters import STRUCTURED_REPORT, RecordedParse, intake_reading, letter_pdf

BIOPSY = {"resource": "Procedure", "subject": "trus biopsy", "value": "Gleason 4+4=8 adenocarcinoma",
          "observed_on": "2023-02-07", "quote": "Gleason 4+4=8, diagnosed on TRUS biopsy 7/2/23"}
HYPERTENSION = {"resource": "Condition", "subject": "hypertension", "value": "present", "observed_on": None,
                "quote": "Hypertension"}


async def version_of(http, patient, run) -> dict:
    return (await http.get(f"/api/patients/{patient}/versions/{run['state']['profile_version_id']}")).json()


async def test_a_date_read_month_first_on_a_day_first_letter_is_sent_back_and_committed_as_the_letter_writes_it(
        clean_db, tmp_path):
    careful = intake_reading([*LETTER_FACTS, BIOPSY, HYPERTENSION])

    def first_read_month_first(lane, system, user):
        out = careful(lane, system, user)
        if "previous answer" not in user:
            out["facts"] = [{**f, "observed_on": "2023-07-02"} if f["subject"] == "trus biopsy" else f
                            for f in out["facts"]]
        return out
    app.state.ctx = letter_ctx(clean_db, tmp_path, first_read_month_first)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        patient, letter, run = await add_letter(http)
        version = await version_of(http, patient, run)
        dating = (await http.get(f"/api/documents/{letter}/regions")).json()

    assert run["state"]["phase"] == "committed"
    [retried] = [e for e in run["events"] if e["kind"] == "intake.retried"]
    assert any("7/2/23" in line and "2023-02-07" in line for line in retried["payload"]["feedback"])
    facts = {f["subject"]: f for f in version["facts"]}
    assert facts["trus biopsy"]["observed_on"] == "2023-02-07", "7/2/23 is 7 February 2023 on this letter"
    assert (dating["date_order"], dating["document_date"]) == ("day_first", "2023-11-23")
    assert (facts["hypertension"]["observed_on"], facts["hypertension"]["flags"]) == ("2023-11-23", ["document_date"])
    assert facts["trus biopsy"]["flags"] == [] and facts["trus biopsy"]["flagged"] is False


REPORT_FACTS = [
    {"resource": "Condition", "subject": "acl tear", "value": "complete tear of the proximal fibres",
     "observed_on": "2026-10-02",
     "quote": "Anterior cruciate ligament: complete tear of the proximal fibres, with no intact fibres in continuity."},
    {"resource": "Observation", "subject": "knee injury", "value": "twisting injury playing netball",
     "observed_on": "2026-10-02", "quote": "Twisting injury playing netball 4 months ago."},
    {"resource": "Observation", "subject": "meniscal tear", "value": "absent", "observed_on": None,
     "quote": "Menisci: No meniscal tear."},
    {"resource": "Observation", "subject": "mcl sprain", "value": "low-grade", "observed_on": None,
     "quote": "3. Low-grade MCL sprain."},
]
"""What a careful Intake model drafts from the structured report: the injury is dated by the model as the report's
date, and two findings carry no date."""


async def test_the_structured_report_is_dated_by_its_service_date_with_its_injury_a_flagged_estimate(
        clean_db, tmp_path):
    ctx = make_ctx(clean_db, FakeLLM(intake_reading(REPORT_FACTS)), parser=RecordedParse(STRUCTURED_REPORT))
    app.state.ctx = replace(ctx, settings=Settings(_env_file=None, pg_dsn=ADMIN_DSN, raw_documents_dir=str(tmp_path)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        patient = (await http.post("/api/patients", json={"label": "Web respondent"})).json()["patient_id"]
        added = await http.post(f"/api/patients/{patient}/documents",
                                files={"file": ("report.pdf", letter_pdf(STRUCTURED_REPORT), "application/pdf")})
        run = (await http.get(f"/api/runs/{added.json()['run_id']}")).json()
        version = await version_of(http, patient, run)
        dating = (await http.get(f"/api/documents/{added.json()['document_hash']}/regions")).json()

    assert run["state"]["phase"] == "committed"
    assert (dating["document_date"], dating["date_order"]) == ("2026-10-02", None), "the date of service"
    facts = {f["subject"]: f for f in version["facts"]}
    injury = facts["knee injury"]
    assert injury["observed_on"].startswith("2026-06"), "about June 2026: 4 months before 02 October 2026"
    assert (injury["flags"], injury["flagged"]) == (["estimated_date"], True)
    meniscus = facts["meniscal tear"]
    assert (meniscus["value"], meniscus["observed_on"], meniscus["flags"]) == ("absent", "2026-10-02", ["document_date"])
    assert meniscus["flagged"] is False
    assert facts["acl tear"]["observed_on"] == "2026-10-02"
    system = ctx.llm.calls[0].system
    assert "absent" in system and "ago" in system, "the one Intake prompt says how to draft both"
