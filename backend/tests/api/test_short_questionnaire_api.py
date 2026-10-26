"""The short questionnaire and a Diagnosis check that can use the letter (#49), through the HTTP API.

The letter is uploaded first and read in the background into drafted Facts that wait for Letter review. The
questionnaire then skips what the letter's Facts answer (the diagnosis and the medicines now) and saves without
waiting for the review. The Diagnosis check reads the questionnaire's diagnosis answer, otherwise the quotes of the
letter's Condition Facts, and waits until both are committed; the Respondent still ticks the labels (ADR 0005).
Nemotron Parse replays recorded, invented Regions and the model is scripted; no network call is made.
"""
from __future__ import annotations

import httpx

from app import trials
from app.llm.nightshift import FakeLLM
from app.main import app
from tests.api.questionnaire_http import submit
from tests.api.test_letter_citations_api import LETTER_FACTS, SNAPSHOT, letter_ctx
from tests.api.test_letter_review_api import review_answers, upload
from tests.fixtures.letters import NARRATIVE_LETTER, intake_reading, letter_pdf

LETTER_DIAGNOSIS = "Metastatic castration-resistant prostate cancer (mCRPC)"   # the letter's Condition Fact quote
SHORT_ANSWERS = {"birth_month": "1958-04", "sex": "male", "postcode": "2000", "max_travel_km": "50",
                 "has_allergies": "yes", "allergies": "penicillin, a rash"}


def reading(lane, system, user):
    """Intake quotes the letter's Regions, or reads a questionnaire's free-text answers; the Diagnosis check offers the
    stored label; the Matcher finds nothing either way and the judge supports every claim."""
    if lane == "fast" and "search phrases" in system:
        return {"phrases": ["lung cancer"]}
    if lane == "fast" and "shortlist" in system:
        return {"labels": ["Non-Small Cell Lung Cancer"]}
    if lane == "fast" and "Intake questionnaire" in user:
        facts = []
        if "penicillin, a rash" in user:
            facts.append({"resource": "AllergyIntolerance", "subject": "penicillin", "value": "rash",
                          "observed_on": "2026-10-24", "page": 5, "quote": "penicillin, a rash", "question": "Q11"})
        if "prostate cancer, spread to the bones" in user:
            facts.append({"resource": "Condition", "subject": "prostate cancer", "value": "metastatic",
                          "observed_on": "2026-10-24", "page": 2, "quote": "prostate cancer, spread to the bones",
                          "question": "Q6"})
        if "Answer: Enantone" in user:
            facts.append({"resource": "MedicationStatement", "subject": "enantone", "value": "taking",
                          "observed_on": "2026-10-24", "page": 4, "quote": "Enantone", "question": "Q9"})
        return {"facts": facts}
    if lane == "fast":
        return intake_reading(LETTER_FACTS)(lane, system, user)
    if lane == "deep":
        return {"results": [{"criterion_id": line.split()[1], "outcome": "unknown", "fact_id": None, "rationale": "x"}
                            for line in user.splitlines() if line.startswith("- NCT")]}
    return {"checks": []}


def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_upload_save_the_short_questionnaire_review_then_check_the_letters_diagnosis_and_rescan(
        clean_db, tmp_path):
    ctx = letter_ctx(clean_db, tmp_path, reading)
    await trials.load_snapshot(ctx, SNAPSHOT)
    app.state.ctx = ctx
    async with client() as http:
        patient, letter, run_id = await upload(http)
        reading_letter = (await http.get(f"/api/patients/{patient}/intake")).json()
        _, saved = await submit(http, patient, SHORT_ANSWERS)
        too_early = await http.post(f"/api/patients/{patient}/questionnaire/diagnosis-check")
        await review_answers(http, run_id, {"prostate cancer": ("keep",)})
        committed = (await http.post(f"/api/runs/{run_id}/review/commit")).json()
        ready = (await http.get(f"/api/patients/{patient}/intake")).json()
        check = await http.post(f"/api/patients/{patient}/questionnaire/diagnosis-check")
        ticked = (await http.post(f"/api/patients/{patient}/questionnaire/diagnosis-check/{check.json()['id']}",
                                  json={"answer": "ticked", "labels": ["Non-Small Cell Lung Cancer"]})).json()
        verdicts = (await http.get(f"/api/patients/{patient}/versions/{committed['profile_version_id']}/verdicts")
                    ).json()

    assert sorted(reading_letter["skip"]) == ["diagnosis", "diagnosis_when", "medicines"]
    assert reading_letter["ready"] is False
    assert [(one["document_hash"], one["filename"], one["run_id"], one["phase"]) for one in reading_letter["letters"]] \
        == [(letter, "letter.pdf", run_id, "awaiting_review")]
    assert (saved["phase"], saved["version_number"]) == ("committed", 1), "saved without waiting for the review"
    assert too_early.status_code == 409, "the Diagnosis check waits for the letter's Facts"
    assert (committed["outcome"], committed["version_number"]) == ("committed", 2)
    assert ready["ready"] is True and ready["letters"][0]["phase"] == "committed"
    assert (ready["profile_version_id"], ready["version_number"]) == (committed["profile_version_id"], 2)

    assert check.status_code == 201
    assert check.json()["text"] == LETTER_DIAGNOSIS, "no diagnosis answer: the letter's Condition Fact quote"
    assert check.json()["shortlist"] == [{"label": "Non-Small Cell Lung Cancer", "open": 1, "closed": 0}]
    [phrases] = [c for c in ctx.llm.calls if "search phrases" in c.system]
    assert LETTER_DIAGNOSIS in phrases.user
    assert ticked["status"] == "ticked" and ticked["rescan"] == {"judged": 1, "failed": 0}
    assert verdicts["condition_term"] == ["Non-Small Cell Lung Cancer"] and len(verdicts["verdicts"]) == 1


async def test_a_short_save_keeps_the_answers_to_questions_it_skipped_and_the_letter_corrections(clean_db, tmp_path):
    ctx = letter_ctx(clean_db, tmp_path, reading)
    await trials.load_snapshot(ctx, SNAPSHOT)
    app.state.ctx = ctx
    async with client() as http:
        patient = (await http.post("/api/patients", json={"label": "Web respondent"})).json()["patient_id"]
        await submit(http, patient, {"diagnosis": "prostate cancer, spread to the bones", "medicines": "Enantone"})
        added = (await http.post(f"/api/patients/{patient}/documents",
                                 files={"file": ("letter.pdf", letter_pdf(NARRATIVE_LETTER), "application/pdf")})).json()
        await review_answers(http, added["run_id"], {"psa": ("drop", "PSA was 12.1 ng/mL")})
        await http.post(f"/api/runs/{added['run_id']}/review/commit")
        skip = (await http.get(f"/api/patients/{patient}/intake")).json()["skip"]
        _, saved = await submit(http, patient, SHORT_ANSWERS)
        version = (await http.get(f"/api/patients/{patient}/versions/{saved['profile_version_id']}")).json()
        answers = (await http.get(f"/api/patients/{patient}/questionnaire")).json()["answers"]
        check = (await http.post(f"/api/patients/{patient}/questionnaire/diagnosis-check")).json()

    assert sorted(skip) == ["diagnosis", "diagnosis_when", "medicines"]
    assert saved["phase"] == "committed"
    reported = {f["citation"]["label"].rsplit(", ", 1)[1] for f in version["facts"] if f["citation"]["span_id"] is None}
    assert {"Q6", "Q9"} <= reported, "a short save does not withdraw the answers to the questions it skipped"
    assert answers["diagnosis"] == "prostate cancer, spread to the bones" and answers["medicines"] == "Enantone"
    assert answers["letter_corrections"] == "psa (the letter was read as 11.2 ng/mL): PSA was 12.1 ng/mL"
    assert answers["birth_month"] == "1958-04"
    assert check["text"] == "prostate cancer, spread to the bones", "the questionnaire's diagnosis answer comes first"


async def test_with_no_letter_nothing_is_skipped_and_a_cleared_answer_is_withdrawn(clean_db):
    from tests.conftest import make_ctx
    app.state.ctx = make_ctx(clean_db, FakeLLM(reading))
    async with client() as http:
        patient = (await http.post("/api/patients", json={"label": "Web respondent"})).json()["patient_id"]
        before = (await http.get(f"/api/patients/{patient}/intake")).json()
        await submit(http, patient, {"diagnosis": "prostate cancer, spread to the bones"})
        _, saved = await submit(http, patient, {"sex": "male"})
        version = (await http.get(f"/api/patients/{patient}/versions/{saved['profile_version_id']}")).json()
        no_diagnosis = await http.post(f"/api/patients/{patient}/questionnaire/diagnosis-check")

    assert before == {"letters": [], "skip": [], "ready": True, "profile_version_id": None, "version_number": None}
    assert [f["citation"]["label"] for f in version["facts"]] == ["Patient-reported, intake questionnaire, Q3"], "a shown question left blank is cleared"
    assert no_diagnosis.status_code == 404


async def test_the_letter_prefill_is_gone(clean_db):
    from tests.conftest import make_ctx
    app.state.ctx = make_ctx(clean_db)
    async with client() as http:
        patient = (await http.post("/api/patients", json={"label": "Web respondent"})).json()["patient_id"]
        prefill = await http.post(f"/api/patients/{patient}/referral/prefill")

    assert prefill.status_code in (404, 405)
