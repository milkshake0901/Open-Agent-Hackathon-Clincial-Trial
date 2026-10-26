"""A free-form question of one trial on the Trials page (#52), for a patient whose Condition term is not prostate cancer.

Through the HTTP API: the structured MRI knee report is added to the Respondent's own patient, they tick an ACL
Condition label, a Re-scan lists the ACL trial, and its trial question cites Regions of the report that open the page
with the Region's box. The answer is not saved and changes no Verdict.

Nemotron Parse replays the recorded, invented report (tests/fixtures/letters.py); the model gives scripted replies.
"""
from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from app import trials
from app.config import Settings
from app.llm.nightshift import FakeLLM
from app.main import app
from tests.condition_term import tick_condition_term
from tests.conftest import ADMIN_DSN, make_ctx
from tests.fixtures.letters import (STRUCTURED_REPORT, STRUCTURED_REPORT_IDENTITY, RecordedParse, intake_reading,
                                    letter_pdf)

NCT = "NCT09000052"
ACL = "Anterior Cruciate Ligament Rupture"
ACL_TRIAL = {"protocolSection": {
    "identificationModule": {"nctId": NCT, "briefTitle": "Early reconstruction after ACL rupture"},
    "statusModule": {"overallStatus": "RECRUITING", "lastUpdatePostDateStruct": {"date": "2026-10-01"}},
    "conditionsModule": {"conditions": [ACL]},
    "eligibilityModule": {"eligibilityCriteria":
        "Inclusion Criteria:\n\n* Complete anterior cruciate ligament tear confirmed on MRI\n\n"
        "Exclusion Criteria:\n\n* Meniscal tear needing repair"}}}

ACL_TEAR = [{"resource": "Condition", "subject": "anterior cruciate ligament tear", "value": "complete",
             "observed_on": "2026-10-02", "quote": "complete tear of the proximal fibres"}]

CITED = ("Anterior cruciate ligament: complete tear", "Menisci: No meniscal tear.")
"""What the scripted trial question cites: two List-item Regions of the report's findings."""


def respond(lane, system, user):
    """Intake reads the ACL tear; the Matcher leaves every Criterion unknown; the trial question cites the shown
    Regions whose words begin one of CITED."""
    if lane == "fast":
        return intake_reading(ACL_TEAR)(lane, system, user)
    if system.startswith("You answer one question about one clinical trial"):
        shown = re.findall(r"^\[(\S+)\] (.*)$", user, re.MULTILINE)
        return {"standing": "possible", "answer": "The MRI shows a complete ACL tear and no meniscal tear.",
                "span_ids": [span for span, text in shown if text.startswith(CITED)],
                "to_gather": ["The date of the injury"]}
    if lane == "judge":
        return {"checks": []}
    return {"results": [{"criterion_id": line.split()[1], "outcome": "unknown", "fact_id": None, "rationale": "-"}
                        for line in user.splitlines() if line.startswith("- NCT")]}


@pytest.fixture
async def knee_patient(clean_db, tmp_path):
    """(http client, ctx, patient id, version id, report hash) for a patient with the MRI knee report and ACL ticked."""
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / f"{NCT}.json").write_text(json.dumps(ACL_TRIAL))
    ctx = make_ctx(clean_db, FakeLLM(respond), parser=RecordedParse(STRUCTURED_REPORT))
    ctx = replace(ctx, settings=Settings(_env_file=None, pg_dsn=ADMIN_DSN, raw_documents_dir=str(tmp_path / "raw")))
    await trials.load_snapshot(ctx, snapshot)
    app.state.ctx = ctx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        patient = (await http.post("/api/patients", json={"label": "Web respondent"})).json()["patient_id"]
        added = await http.post(f"/api/patients/{patient}/documents",
                                files={"file": ("mri-knee.pdf", letter_pdf(STRUCTURED_REPORT), "application/pdf")})
        assert added.status_code == 202, added.text
        run = (await http.get(f"/api/runs/{added.json()['run_id']}")).json()
        assert run["state"]["phase"] == "committed"
        await tick_condition_term(ctx, patient, labels=[ACL])
        vid = run["state"]["profile_version_id"]
        await http.post(f"/api/patients/{patient}/versions/{vid}/rescan")
        yield http, ctx, patient, vid, added.json()["document_hash"]


async def test_a_trial_question_from_the_trials_page_cites_report_regions_that_open_the_page_with_their_box(
        knee_patient):
    http, ctx, patient, vid, report = knee_patient
    listed = (await http.get(f"/api/patients/{patient}/versions/{vid}/verdicts")).json()
    assert listed["condition_term"] == [ACL]
    assert [v["nct_id"] for v in listed["verdicts"]] == [NCT]

    asked = await http.post(f"/api/patients/{patient}/trials/{NCT}/ask",
                            json={"question": "Could this trial suit me?"})
    assert asked.status_code == 200, asked.text
    body = asked.json()
    regions = {r["span_id"]: r for r in (await http.get(f"/api/documents/{report}/regions")).json()["regions"]}

    assert (body["nct_id"], body["standing"], body["to_gather"]) == (NCT, "possible", ["The date of the injury"])
    assert [c["quote"][:len(start)] for c, start in zip(body["citations"], CITED)] == list(CITED)
    for c in body["citations"]:
        region = regions[c["span_id"]]
        assert region["kind"] == "List-item"
        assert (c["document_hash"], c["filename"], c["page"], c["quote"]) == (report, "mri-knee.pdf", 1, region["text"])
        assert (c["x0"], c["y0"], c["x1"], c["y1"]) == pytest.approx(
            (region["x0"], region["y0"], region["x1"], region["y1"]))
    image = await http.get(f"/api/documents/{report}/pages/1/image")
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"


async def test_the_trial_question_shows_the_model_every_region_intake_reads_and_no_letterhead_or_identity(
        knee_patient):
    http, ctx, patient, _, _ = knee_patient
    await http.post(f"/api/patients/{patient}/trials/{NCT}/ask", json={"question": "Could this trial suit me?"})

    [prompt] = [c.user for c in ctx.llm.calls if c.system.startswith("You answer one question")]
    for shown in ("MRI LEFT KNEE", "Findings", "Menisci: No meniscal tear.", "| Date of service | 02 October 2026 |",
                  "Twisting injury playing netball"):
        assert shown in prompt
    assert "7 Pier Street" not in prompt, "a Page-footer is letterhead, not evidence"
    assert not [i for i in STRUCTURED_REPORT_IDENTITY if i in prompt]


async def test_a_trial_question_is_not_saved_and_changes_no_verdict(knee_patient):
    http, _, patient, vid, _ = knee_patient
    before = (await http.get(f"/api/patients/{patient}/versions/{vid}/verdicts")).json()
    asked = await http.post(f"/api/patients/{patient}/trials/{NCT}/ask", json={"question": "Am I eligible?"})
    after = (await http.get(f"/api/patients/{patient}/versions/{vid}/verdicts")).json()

    assert asked.status_code == 200
    assert after == before
