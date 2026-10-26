"""Letter review before a letter's Facts are committed (#48), through the HTTP API.

A letter added to the Respondent's own patient is read page by page (a scripted Intake model quoting its Regions); its
drafted Facts then wait, uncommitted, in the ingest run (phase awaiting_review). The Respondent keeps or drops each,
says what a dropped one should be, corrects the Document date, and commits; or uses them all as read. Nemotron Parse
replays recorded, invented Regions; no network call is made.
"""
from __future__ import annotations

from dataclasses import replace

import httpx

from app import trials
from app.config import Settings
from app.llm.nightshift import FakeLLM
from app.main import app
from tests.api.questionnaire_http import submit
from tests.api.test_letter_citations_api import LETTER_FACTS, SNAPSHOT, judging_the_letter, letter_ctx
from tests.condition_term import tick_condition_term
from tests.api.test_letter_dates_api import REPORT_FACTS
from tests.conftest import ADMIN_DSN, make_ctx
from tests.fixtures.letters import (
    NARRATIVE_LETTER, STRUCTURED_REPORT, RecordedParse, intake_reading, letter_pdf, recorded, recording,
)


async def upload(http, document=NARRATIVE_LETTER, filename="letter.pdf") -> tuple[str, str, str]:
    """A Respondent's own patient with a letter added: (patient id, document hash, run id)."""
    patient = (await http.post("/api/patients", json={"label": "Web respondent"})).json()["patient_id"]
    added = await http.post(f"/api/patients/{patient}/documents",
                            files={"file": (filename, letter_pdf(document), "application/pdf")})
    assert added.status_code == 202
    return patient, added.json()["document_hash"], added.json()["run_id"]


def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_a_letters_drafted_facts_wait_uncommitted_for_review_each_beside_its_region(clean_db, tmp_path):
    app.state.ctx = letter_ctx(clean_db, tmp_path, intake_reading(LETTER_FACTS))
    async with client() as http:
        patient, letter, run_id = await upload(http)
        run = (await http.get(f"/api/runs/{run_id}")).json()
        review = (await http.get(f"/api/runs/{run_id}/review")).json()
        regions = {r["span_id"]: r for r in (await http.get(f"/api/documents/{letter}/regions")).json()["regions"]}

    assert run["state"]["phase"] == "awaiting_review"
    assert run["state"]["profile_version_id"] is None
    assert (review["run_id"], review["document_hash"], review["filename"]) == (run_id, letter, "letter.pdf")
    assert (review["document_date"], review["date_order"], review["page_count"]) == ("2023-11-23", "day_first", 3)
    assert sorted(f["subject"] for f in review["facts"]) == sorted(f["subject"] for f in LETTER_FACTS)
    for fact in review["facts"]:
        region = regions[fact["region"]["span_id"]]
        assert (fact["page"], fact["region"]["text"], fact["region"]["kind"]) == (region["page"], region["text"],
                                                                                   region["kind"])
        assert fact["region"]["x0"] == region["x0"] and fact["region"]["y1"] == region["y1"]
        assert fact["decision"] is None and fact["correction"] is None
    psa = next(f for f in review["facts"] if f["subject"] == "psa")
    assert (psa["value"], psa["unit"], psa["observed_on"]) == ("11.2", "ng/mL", "2023-11-20")


PSA_CORRECTION = {"resource": "Observation", "subject": "psa", "value": "12.1", "unit": "ng/mL",
                  "observed_on": "2023-11-20", "page": 9, "quote": "PSA was 12.1 ng/mL on 20/11/23", "question": "Q16"}
"""What the Intake agent drafts from the correction answer, as a Patient-reported Fact."""


def reading_letter_and_corrections(lane, system, user):
    """Intake on the letter quotes its Regions; on a questionnaire, it reads the corrections answer."""
    if "Intake questionnaire" in user:
        return {"facts": [PSA_CORRECTION] if "PSA was 12.1" in user else []}
    return intake_reading(LETTER_FACTS)(lane, system, user)


async def review_answers(http, run_id, answers: dict[str, tuple]) -> dict:
    """Answer the review by subject: {subject: ("keep",) | ("drop", correction or None)}; the review after."""
    review = (await http.get(f"/api/runs/{run_id}/review")).json()
    for fact in review["facts"]:
        if fact["subject"] in answers:
            decision, *correction = answers[fact["subject"]]
            answered = await http.post(f"/api/runs/{run_id}/review/facts/{fact['index']}",
                                       json={"decision": decision, "correction": correction[0] if correction else None})
            assert answered.status_code == 200, answered.text
            review = answered.json()
    return review


async def test_a_dropped_fact_is_never_committed_and_its_correction_becomes_a_patient_reported_fact(
        clean_db, tmp_path):
    ctx = letter_ctx(clean_db, tmp_path, reading_letter_and_corrections)
    app.state.ctx = ctx
    async with client() as http:
        patient, letter, run_id = await upload(http)
        review = await review_answers(http, run_id, {
            "prostate cancer": ("keep",), "gleason score": ("keep",),
            "psa": ("drop", "PSA was 12.1 ng/mL on 20/11/23")})
        committed = await http.post(f"/api/runs/{run_id}/review/commit")
        run = (await http.get(f"/api/runs/{run_id}")).json()
        letter_version = (await http.get(f"/api/patients/{patient}/versions/{run['state']['profile_version_id']}")).json()
        correction_run = (await http.get(f"/api/runs/{committed.json()['correction_run_id']}")).json()
        latest = (await http.get(f"/api/patients/{patient}/versions/"
                                 f"{correction_run['state']['profile_version_id']}")).json()
        answers = (await http.get(f"/api/patients/{patient}/questionnaire")).json()
        again = await http.post(f"/api/runs/{run_id}/review/commit")

    psa = next(f for f in review["facts"] if f["subject"] == "psa")
    assert (psa["decision"], psa["correction"]) == ("drop", "PSA was 12.1 ng/mL on 20/11/23")
    assert committed.status_code == 202
    assert (committed.json()["outcome"], committed.json()["version_number"]) == ("committed", 1)
    assert run["state"]["phase"] == "committed"
    by_subject = {f["subject"]: f for f in letter_version["facts"]}
    assert "psa" not in by_subject, "a Fact marked Not right is never committed"
    assert sorted(by_subject) == sorted(f["subject"] for f in LETTER_FACTS if f["subject"] != "psa")
    checked = {s: f["citation"]["checked"] for s, f in by_subject.items()}
    assert checked == {"prostate cancer": True, "gleason score": True, "enantone": False,
                       "ecog performance status": False, "penicillin": False}

    assert correction_run["state"]["phase"] == "committed" and correction_run["state"]["version_number"] == 2
    [reported] = [f for f in latest["facts"] if f["subject"] == "psa"]
    assert (reported["value"], reported["unit"], reported["citation"]["label"]) == (
        "12.1", "ng/mL", "Patient-reported, intake questionnaire, Q16")
    assert reported["citation"]["checked"] is None
    assert not [f for f in latest["facts"] if f["subject"] == "psa" and f["citation"]["document_hash"] == letter]
    assert answers["answers"]["letter_corrections"] == (
        "psa (the letter was read as 11.2 ng/mL): PSA was 12.1 ng/mL on 20/11/23")
    assert again.status_code == 409, "a review commits once"


async def test_a_later_questionnaire_save_that_leaves_the_corrections_blank_keeps_them(clean_db, tmp_path):
    app.state.ctx = letter_ctx(clean_db, tmp_path, reading_letter_and_corrections)
    async with client() as http:
        patient, _, run_id = await upload(http)
        await review_answers(http, run_id, {"psa": ("drop", "PSA was 12.1 ng/mL on 20/11/23")})
        await http.post(f"/api/runs/{run_id}/review/commit")
        _, saved = await submit(http, patient, {"sex": "male"})
        version = (await http.get(f"/api/patients/{patient}/versions/{saved['profile_version_id']}")).json()

    assert saved["phase"] == "committed" and saved["version_number"] == 3
    reported = {f["subject"]: f["citation"]["label"] for f in version["facts"] if f["citation"]["span_id"] is None}
    assert reported == {"psa": "Patient-reported, intake questionnaire, Q16",
                        "sex assigned at birth": "Patient-reported, intake questionnaire, Q3"}


async def test_use_all_as_read_commits_every_drafted_fact_not_checked(clean_db, tmp_path):
    app.state.ctx = letter_ctx(clean_db, tmp_path, intake_reading(LETTER_FACTS))
    async with client() as http:
        patient, _, run_id = await upload(http)
        await review_answers(http, run_id, {"psa": ("drop", "PSA was 12.1"), "gleason score": ("keep",)})
        used = await http.post(f"/api/runs/{run_id}/review/use-all-as-read")
        version = (await http.get(f"/api/patients/{patient}/versions/{used.json()['profile_version_id']}")).json()
        answers = await http.get(f"/api/patients/{patient}/questionnaire")

    assert used.status_code == 202 and used.json()["outcome"] == "committed"
    assert used.json()["correction_run_id"] is None
    assert sorted(f["subject"] for f in version["facts"]) == sorted(f["subject"] for f in LETTER_FACTS)
    assert {f["citation"]["checked"] for f in version["facts"]} == {False}
    assert answers.status_code == 404 or answers.json() is None, "no correction was made into an answer"


async def test_a_criterion_results_citation_shows_whether_its_letter_fact_was_checked(clean_db, tmp_path):
    ctx = letter_ctx(clean_db, tmp_path, judging_the_letter(intake_reading(LETTER_FACTS)))
    await trials.load_snapshot(ctx, SNAPSHOT)
    app.state.ctx = ctx
    async with client() as http:
        patient, _, run_id = await upload(http)
        await review_answers(http, run_id, {"ecog performance status": ("keep",)})
        vid = (await http.post(f"/api/runs/{run_id}/review/commit")).json()["profile_version_id"]
        await tick_condition_term(ctx, patient)
        await http.post(f"/api/patients/{patient}/versions/{vid}/rescan")
        [verdict] = (await http.get(f"/api/patients/{patient}/versions/{vid}/verdicts")).json()["verdicts"]

    cited = {r["outcome"]: r["citation"] for r in verdict["results"] if r["outcome"] != "unknown"}
    assert cited["met"]["checked"] is True, "ECOG, marked Looks right: checked by you"
    assert cited["not_met"]["checked"] is False, "prostate cancer, left as read: not checked"


def report_ctx(clean_db, tmp_path):
    ctx = make_ctx(clean_db, FakeLLM(intake_reading(REPORT_FACTS)), parser=RecordedParse(STRUCTURED_REPORT))
    return replace(ctx, settings=Settings(_env_file=None, pg_dsn=ADMIN_DSN, raw_documents_dir=str(tmp_path)))


async def test_flagged_facts_come_first_and_a_corrected_document_date_re_dates_the_facts_it_dated(clean_db, tmp_path):
    app.state.ctx = report_ctx(clean_db, tmp_path)
    async with client() as http:
        patient, report, run_id = await upload(http, STRUCTURED_REPORT, "report.pdf")
        before = (await http.get(f"/api/runs/{run_id}/review")).json()
        corrected = await http.put(f"/api/runs/{run_id}/review/document-date", json={"document_date": "2026-09-30"})
        regions = (await http.get(f"/api/documents/{report}/regions")).json()
        vid = (await http.post(f"/api/runs/{run_id}/review/use-all-as-read")).json()["profile_version_id"]
        version = (await http.get(f"/api/patients/{patient}/versions/{vid}")).json()

    assert before["facts"][0]["subject"] == "knee injury" and before["facts"][0]["flagged"] is True
    assert [f["flagged"] for f in before["facts"]] == [True, False, False, False], "flagged Facts first"
    assert (before["document_date"], before["document_date_corrected"]) == ("2026-10-02", False)
    assert corrected.status_code == 200
    after = {f["subject"]: f for f in corrected.json()["facts"]}
    assert (corrected.json()["document_date"], corrected.json()["document_date_corrected"]) == ("2026-09-30", True)
    assert after["meniscal tear"]["observed_on"] == "2026-09-30", "no date of its own: the Document date"
    assert after["knee injury"]["observed_on"] == "2026-05-30", "4 months before the corrected date"
    assert after["acl tear"]["observed_on"] == "2026-10-02", "a date of its own is kept"
    assert regions["document_date"] == "2026-09-30"
    committed = {f["subject"]: f["observed_on"] for f in version["facts"]}
    assert committed == {"meniscal tear": "2026-09-30", "mcl sprain": "2026-09-30", "knee injury": "2026-05-30",
                         "acl tear": "2026-10-02"}


async def test_review_calls_that_do_not_fit_are_refused(clean_db, tmp_path):
    app.state.ctx = report_ctx(clean_db, tmp_path)
    async with client() as http:
        _, _, run_id = await upload(http, STRUCTURED_REPORT, "report.pdf")
        no_such_fact = await http.post(f"/api/runs/{run_id}/review/facts/99", json={"decision": "keep"})
        kept_with_correction = await http.post(f"/api/runs/{run_id}/review/facts/0",
                                               json={"decision": "keep", "correction": "it was 2025"})
        future_date = await http.put(f"/api/runs/{run_id}/review/document-date", json={"document_date": "2027-01-01"})
        unknown_run = await http.get("/api/runs/run_unknown/review")
        await http.post(f"/api/runs/{run_id}/review/use-all-as-read")
        after_commit = await http.get(f"/api/runs/{run_id}/review")
        late_answer = await http.post(f"/api/runs/{run_id}/review/facts/0", json={"decision": "drop"})

    assert (no_such_fact.status_code, kept_with_correction.status_code, future_date.status_code) == (422, 422, 422)
    assert unknown_run.status_code == 404
    assert (after_commit.status_code, late_answer.status_code) == (409, 409)


async def test_adding_the_same_letter_again_answers_with_the_run_still_waiting_for_review(clean_db, tmp_path):
    app.state.ctx = letter_ctx(clean_db, tmp_path, intake_reading(LETTER_FACTS))
    async with client() as http:
        patient, letter, run_id = await upload(http)
        again = await http.post(f"/api/patients/{patient}/documents",
                                files={"file": ("letter.pdf", letter_pdf(NARRATIVE_LETTER), "application/pdf")})

    assert (again.json()["run_id"], again.json()["deduplicated"]) == (run_id, True)


async def test_a_letter_with_a_conflict_goes_to_review_once_the_conflict_is_resolved(clean_db, tmp_path):
    second = recording("Date of service: 02 October 2026\nMenisci: meniscal tear present.")
    torn = {"resource": "Observation", "subject": "meniscal tear", "value": "present", "observed_on": None,
            "quote": "Menisci: meniscal tear present."}
    ctx = make_ctx(clean_db, FakeLLM(intake_reading([*REPORT_FACTS, torn])),
                   parser=recorded((letter_pdf(STRUCTURED_REPORT), STRUCTURED_REPORT), (letter_pdf(second, "b"), second)))
    app.state.ctx = replace(ctx, settings=Settings(_env_file=None, pg_dsn=ADMIN_DSN, raw_documents_dir=str(tmp_path)))
    async with client() as http:
        patient, _, first_run = await upload(http, STRUCTURED_REPORT, "report.pdf")
        await http.post(f"/api/runs/{first_run}/review/use-all-as-read")
        added = (await http.post(f"/api/patients/{patient}/documents",
                                 files={"file": ("second.pdf", letter_pdf(second, "b"), "application/pdf")})).json()
        [conflict] = (await http.get(f"/api/runs/{added['run_id']}/conflicts")).json()["conflicts"]
        confirmed = await http.post(f"/api/runs/{added['run_id']}/confirm",
                                    json={"resolutions": [{"conflict_id": conflict["id"], "choice": "accept_draft"}]})
        review = (await http.get(f"/api/runs/{added['run_id']}/review")).json()
        await review_answers(http, added["run_id"], {"meniscal tear": ("keep",)})
        vid = (await http.post(f"/api/runs/{added['run_id']}/review/commit")).json()["profile_version_id"]
        version = (await http.get(f"/api/patients/{patient}/versions/{vid}")).json()

    assert confirmed.json()["outcome"] == "awaiting_review"
    assert [f["subject"] for f in review["facts"]] == ["meniscal tear"]
    meniscus = [f for f in version["facts"] if f["subject"] == "meniscal tear"]
    assert [(f["value"], f["citation"]["checked"]) for f in meniscus] == [("present", True)], (
        "the accepted Fact the Respondent overruled is left out")
