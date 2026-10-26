"""A letter's Facts cite their Region, all the way to the Trials page (#46).

Through the HTTP API: the narrative letter fixture is added to the Respondent's own patient, Intake reads it one page
at a time (a scripted model that quotes Regions), and the committed Facts each name a Region of that letter. A Re-scan
then gives Criterion results whose Citation opens the letter page with the Region's box.

Nemotron Parse replays recorded, invented Regions (tests/fixtures/letters.py); no network call is made.
"""
from __future__ import annotations

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
from tests.review import use_all_as_read
from tests.fixtures.letters import NARRATIVE_LETTER, NARRATIVE_LETTER_IDENTITY, RecordedParse, intake_reading, letter_pdf

SNAPSHOT = Path(__file__).resolve().parents[3] / "data" / "trials_snapshot"

LETTER_FACTS = [
    {"resource": "Condition", "subject": "prostate cancer", "value": "metastatic castration-resistant",
     "observed_on": "2023-11-23", "quote": "Metastatic castration-resistant prostate cancer (mCRPC)"},
    {"resource": "Observation", "subject": "gleason score", "value": "4+4=8", "observed_on": "2023-02-07",
     "quote": "Gleason 4+4=8"},
    {"resource": "MedicationStatement", "subject": "enantone", "value": "3-monthly injections",
     "observed_on": "2023-03-01", "quote": "Enantone (leuprorelin) 3-monthly injections, started 1/3/23"},
    {"resource": "Observation", "subject": "psa", "value": "11.2", "unit": "ng/mL", "observed_on": "2023-11-20",
     "quote": "11.2 ng/mL on 20/11/23"},
    {"resource": "Observation", "subject": "ecog performance status", "value": "1", "observed_on": "2023-11-23",
     "quote": "I would estimate his ECOG performance status at 1."},
    {"resource": "AllergyIntolerance", "subject": "penicillin", "value": "rash", "observed_on": "2023-11-23",
     "quote": "Penicillin (rash)"},
]
"""What a careful Intake model drafts from the narrative letter: quotes from all three pages."""


def letter_ctx(clean_db, tmp_path, responder):
    ctx = make_ctx(clean_db, FakeLLM(responder), parser=RecordedParse(NARRATIVE_LETTER))
    return replace(ctx, settings=Settings(_env_file=None, pg_dsn=ADMIN_DSN, raw_documents_dir=str(tmp_path)))


async def add_letter(http) -> tuple[str, str, dict]:
    """A Respondent's own patient with the narrative letter added and its Letter review skipped (all as read):
    (patient id, document hash, the run)."""
    patient = (await http.post("/api/patients", json={"label": "Web respondent"})).json()["patient_id"]
    added = await http.post(f"/api/patients/{patient}/documents",
                            files={"file": ("letter.pdf", letter_pdf(NARRATIVE_LETTER), "application/pdf")})
    assert added.status_code == 202
    run = await use_all_as_read(http, added.json()["run_id"])
    return patient, added.json()["document_hash"], run


async def test_a_letter_is_read_one_page_at_a_time_and_each_committed_fact_cites_a_region_of_it(clean_db, tmp_path):
    ctx = letter_ctx(clean_db, tmp_path, intake_reading(LETTER_FACTS))
    app.state.ctx = ctx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        patient, letter, run = await add_letter(http)
        assert (run["state"]["phase"], run["state"]["version_number"]) == ("committed", 1)
        version = (await http.get(f"/api/patients/{patient}/versions/{run['state']['profile_version_id']}")).json()
        regions = {r["span_id"]: r for r in (await http.get(f"/api/documents/{letter}/regions")).json()["regions"]}

    assert sorted(f["subject"] for f in version["facts"]) == sorted(f["subject"] for f in LETTER_FACTS)
    for fact in version["facts"]:
        cited = fact["citation"]
        region = regions[cited["span_id"]]
        assert cited["document_hash"] == letter and cited["page"] == region["page"]
        assert " ".join(cited["quote"].split()).lower() in " ".join(region["text"].split()).lower()
    assert {f["subject"]: f["citation"]["page"] for f in version["facts"]}["penicillin"] == 3

    intake = [c for c in ctx.llm.calls if c.lane == "fast"]
    assert len(intake) == 3, "one Intake call per page"
    assert len({c.system for c in intake}) == 1, "one prompt for every page"
    shown = "\n".join(c.user for c in intake)
    for kind in ("Page-header", "Page-footer", "Picture"):
        assert f"({kind})" not in shown
    assert "Page 1 of 3" not in shown and "|||" not in shown
    for kind in ("Text", "Title", "Section-header", "List-item", "Table", "Caption"):
        assert f"({kind})" in shown
    assert not [i for i in NARRATIVE_LETTER_IDENTITY if i in shown]


async def test_a_draft_naming_no_region_of_the_letter_is_sent_back_and_only_its_page_is_read_again(clean_db, tmp_path):
    careful = intake_reading(LETTER_FACTS)

    def first_guess_invented(lane, system, user):
        out = careful(lane, system, user)
        if "previous answer" not in user and "ECOG performance status" in user:
            out["facts"] = [{**f, "span_id": "invented:p2:b99"} if f["subject"] == "ecog performance status" else f
                            for f in out["facts"]]
        return out
    ctx = letter_ctx(clean_db, tmp_path, first_guess_invented)
    app.state.ctx = ctx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        patient, _, run = await add_letter(http)
        version = (await http.get(f"/api/patients/{patient}/versions/{run['state']['profile_version_id']}")).json()

    assert run["state"]["phase"] == "committed"
    retried = [e for e in run["events"] if e["kind"] == "intake.retried"]
    assert len(retried) == 1 and "invented:p2:b99" in retried[0]["payload"]["feedback"][0]
    intake = [c.user for c in ctx.llm.calls if c.lane == "fast"]
    assert len(intake) == 4 and "--- Page 2 ---" in intake[3] and "invented:p2:b99" in intake[3]
    ecog = next(f for f in version["facts"] if f["subject"] == "ecog performance status")
    assert ecog["citation"]["span_id"].endswith(":p2:b6") and ecog["citation"]["page"] == 2
    assert len(version["facts"]) == len(LETTER_FACTS)


def judging_the_letter(intake):
    """Intake as given; the Matcher finds ECOG met on the letter's performance status and the NSCLC Criterion not met
    on its prostate cancer, everything else unknown; the judge supports every claim."""
    cited = {"ECOG": ("met", "ecog performance status"), "NSCLC": ("not_met", "prostate cancer")}

    def respond(lane, system, user):
        if lane == "fast":
            return intake(lane, system, user)
        if lane == "judge":
            return {"checks": [{"criterion_id": line.split()[1], "supported": True}
                               for line in user.splitlines() if line.startswith("CLAIM ")]}
        facts = {line.split(" | ")[1].split(":")[0]: line.split()[1]
                 for line in user.splitlines() if line.startswith("- fact:")}
        results = []
        for line in (line for line in user.splitlines() if line.startswith("- NCT")):
            word = next((w for w in cited if w in line), None)
            outcome, subject = cited[word] if word else ("unknown", None)
            results.append({"criterion_id": line.split()[1], "outcome": outcome,
                            "fact_id": facts[subject] if subject else None, "rationale": "per the letter"})
        return {"results": results}
    return respond


async def test_a_criterion_result_citing_a_letter_fact_opens_its_document_page_and_region_box(clean_db, tmp_path):
    ctx = letter_ctx(clean_db, tmp_path, judging_the_letter(intake_reading(LETTER_FACTS)))
    await trials.load_snapshot(ctx, SNAPSHOT)
    app.state.ctx = ctx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        patient, letter, run = await add_letter(http)
        vid = run["state"]["profile_version_id"]
        await tick_condition_term(ctx, patient)
        await http.post(f"/api/patients/{patient}/versions/{vid}/rescan")
        [verdict] = (await http.get(f"/api/patients/{patient}/versions/{vid}/verdicts")).json()["verdicts"]
        regions = {r["span_id"]: r for r in (await http.get(f"/api/documents/{letter}/regions")).json()["regions"]}
        page_image = await http.get(f"/api/documents/{letter}/pages/2/image")

    by_outcome = {r["outcome"]: r for r in verdict["results"] if r["outcome"] != "unknown"}
    met, not_met = by_outcome["met"]["citation"], by_outcome["not_met"]["citation"]
    assert "ECOG" in by_outcome["met"]["text"] and "NSCLC" in by_outcome["not_met"]["text"]
    for citation, page in ((met, 2), (not_met, 1)):
        region = regions[citation["region"]["span_id"]]
        assert (citation["document_hash"], citation["filename"], citation["page"]) == (letter, "letter.pdf", page)
        assert region["page"] == page
        assert citation["region"] == pytest.approx(
            {"span_id": region["span_id"], "x0": region["x0"], "y0": region["y0"], "x1": region["x1"],
             "y1": region["y1"]})
        assert citation["label"] == f"page {page}"
        assert citation["question"] is None and citation["answer"] is None
    assert met["region"] == pytest.approx({"span_id": met["region"]["span_id"], "x0": 0.08, "y0": 0.44, "x1": 0.92,
                                           "y1": 0.52}), "the recorded box of the ECOG sentence"
    assert page_image.status_code == 200 and page_image.headers["content-type"] == "image/png"
    assert verdict["outcome"] == "excluded"
