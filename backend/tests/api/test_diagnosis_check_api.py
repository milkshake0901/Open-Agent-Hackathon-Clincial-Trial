"""HTTP smoke test for the Diagnosis check (#14, #33): a shortlist of Condition labels, the answers, and the
patient-level Doctor question.
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
    if lane == "fast" and "search phrases" in system:
        return {"phrases": ["lung cancer"]}
    if lane == "fast" and "shortlist" in system:
        return {"labels": ["Non-Small Cell Lung Cancer"]}
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
        verdicts = f"/api/patients/{patient}/versions/{vid}/verdicts"
        unchecked = (await http.get(verdicts)).json()
        assert unchecked["condition_term"] is None and unchecked["verdicts"] == []
        assert unchecked["diagnosis"] == "unfinished"

        proposed = await http.post(url)
        assert proposed.status_code == 201
        body = proposed.json()
        assert body["status"] == "proposed" and body["ticked"] == []
        assert body["shortlist"] == [{"label": "Non-Small Cell Lung Cancer", "open": 1, "closed": 0}]
        assert "Tick" in body["message"]

        answer = f"{url}/{body['id']}"
        assert (await http.post(answer, json={"answer": "ticked", "labels": ["Breast Cancer"]})).status_code == 422
        for wrong in ({"answer": "maybe"}, {"answer": "ticked"}, {"answer": "ticked", "labels": []},
                      {"answer": "none_of_these"}, {"answer": "none_of_these", "text": "  "}, {}):
            assert (await http.post(answer, json=wrong)).status_code == 422, wrong
        again = (await http.post(answer, json={"answer": "none_of_these", "text": "NSCLC"})).json()
        assert again["id"] != body["id"] and again["text"] == "NSCLC" and again["status"] == "proposed"
        assert (await http.post(answer, json={"answer": "ticked", "labels": ["Non-Small Cell Lung Cancer"]})
                ).status_code == 409

        ticked = (await http.post(f"{url}/{again['id']}", json={"answer": "ticked",
                                                                "labels": ["non-small cell lung cancer"]})).json()
        assert ticked["status"] == "ticked" and ticked["ticked"] == ["Non-Small Cell Lung Cancer"]
        assert ticked["rescan"] == {"judged": 1, "failed": 0}
        assert "Non-Small Cell Lung Cancer" in ticked["message"]
        assert (await http.get(verdicts)).json()["diagnosis"] == "ticked"

        third = (await http.post(url)).json()
        unsure = (await http.post(f"{url}/{third['id']}", json={"answer": "not_sure"})).json()
        assert unsure["needs_gp"] is True and "GP" in unsure["message"] and unsure["rescan"] is None
        listed = (await http.get(verdicts)).json()
        assert listed["diagnosis"] == "not_sure" and listed["condition_term"] is None and listed["verdicts"] == []

        questions = (await http.get(f"/api/patients/{patient}/questions", params={"version": vid})).json()
        assert questions[0]["criterion_id"] is None and questions[0]["nct_id"] is None
        assert questions[0]["subject"] == "diagnosis" and questions[0]["unblocks"] == []

        assert (await http.post("/api/patients/pt_nobody/questionnaire/diagnosis-check")).status_code == 404


async def test_each_diagnosis_check_step_writes_a_line_to_the_log_file(clean_db, tmp_path):
    import json

    from app import logfile
    from tests.conftest import make_ctx
    ctx = make_ctx(clean_db, FakeLLM(respond))
    await trials.load_snapshot(ctx, SNAPSHOT)
    app.state.ctx = ctx
    path = tmp_path / "trialmatch.jsonl"
    logfile.configure(path)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
            patient = (await http.post("/api/patients", json={"label": "Demo patient H"})).json()["patient_id"]
            await submit(http, patient, {"diagnosis": DIAGNOSIS})
            url = f"/api/patients/{patient}/questionnaire/diagnosis-check"
            check = (await http.post(url)).json()
            tick = {"answer": "ticked", "labels": ["Non-Small Cell Lung Cancer"]}
            assert (await http.post(f"{url}/{check['id']}", json=tick)).status_code == 200
    finally:
        logfile.reset()

    steps = {s["step"]: s for s in map(json.loads, path.read_text().splitlines())}
    offered, answered = steps["record.diagnosis_check.offered"], steps["record.diagnosis_check.answered"]
    assert offered["patient_id"] == answered["patient_id"] == patient
    assert offered["check"]["id"] == answered["check"]["id"] == check["id"]
    assert offered["check"]["shortlist"] == [{"label": "Non-Small Cell Lung Cancer", "open": 1, "closed": 0}]
    assert answered["answer"] == {**tick, "text": None}
    assert answered["check"]["ticked"] == ["Non-Small Cell Lung Cancer"]
    assert "Demo patient H" not in path.read_text()
