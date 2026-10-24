"""HTTP smoke test for the diagnosis check (#14): propose, answer, and the patient-level Doctor question.
Behaviour is covered in tests/record and tests/matching; this only checks the wiring."""
from __future__ import annotations

from pathlib import Path

import httpx

from app import trials
from app.main import app
from tests.api.questionnaire_http import submit
from app.llm.nightshift import FakeLLM

SNAPSHOT = Path(__file__).resolve().parents[3] / "data" / "trials_snapshot"
DIAGNOSIS = "lung cancer, the non small cell kind"


def respond(lane, system, user):
    if lane == "fast" and "condition term" in system:
        return {"term": "non-small cell lung cancer", "confidence": 0.9}
    if lane == "fast":
        return {"facts": [{"resource": "Condition", "subject": "lung cancer", "value": "non-small cell",
                           "observed_on": "2026-10-24", "page": 2, "quote": DIAGNOSIS, "question": "Q6"}]}
    if lane == "deep":
        return {"results": [{"criterion_id": line.split()[1], "outcome": "unknown", "fact_id": None, "rationale": "x"}
                            for line in user.splitlines() if line.startswith("- NCT")]}
    return {"checks": []}


async def test_propose_answer_and_list_the_diagnosis_doctor_question(clean_db):
    from tests.conftest import make_ctx
    ctx = make_ctx(clean_db, FakeLLM(respond))
    await trials.load_snapshot(ctx, SNAPSHOT)
    app.state.ctx = ctx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        patient = (await http.post("/api/patients", json={"label": "Demo patient H"})).json()["patient_id"]
        _, state = await submit(http, patient, {"diagnosis": DIAGNOSIS})
        vid = state["profile_version_id"]
        url = f"/api/patients/{patient}/questionnaire/diagnosis-check"

        proposed = await http.post(url, json={})
        assert proposed.status_code == 201
        body = proposed.json()
        assert body["suggested_term"] == "non-small cell lung cancer" and body["status"] == "proposed"
        assert body["message"] == "We understood this as non-small cell lung cancer. Is that right?"

        rejected = (await http.post(f"{url}/{body['id']}", json={"answer": "no"})).json()
        assert rejected["status"] == "rejected" and rejected["ask_again"] is True
        assert (await http.post(f"{url}/{body['id']}", json={"answer": "yes"})).status_code == 409
        assert (await http.post(f"{url}/{body['id']}", json={"answer": "maybe"})).status_code == 422

        again = (await http.post(url, json={"text": "NSCLC"})).json()
        confirmed = (await http.post(f"{url}/{again['id']}", json={"answer": "yes"})).json()
        assert confirmed["condition"] == "non-small cell lung cancer" and confirmed["rescan"] == {"judged": 0, "failed": 0}

        third = (await http.post(url, json={"text": "not sure, something in the lung"})).json()
        unsure = (await http.post(f"{url}/{third['id']}", json={"answer": "not_sure"})).json()
        assert unsure["needs_gp"] is True and "GP" in unsure["message"]

        questions = (await http.get(f"/api/patients/{patient}/questions", params={"version": vid})).json()
        assert questions[0]["criterion_id"] is None and questions[0]["nct_id"] is None
        assert questions[0]["subject"] == "diagnosis" and questions[0]["unblocks"] == []

        assert (await http.post("/api/patients/pt_nobody/questionnaire/diagnosis-check", json={})).status_code == 404
