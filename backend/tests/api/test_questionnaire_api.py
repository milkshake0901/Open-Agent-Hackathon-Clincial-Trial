"""HTTP smoke test of the tracer: definition → patient → submit → Profile v1 with questionnaire Citations.
The routes only call the record facade; behaviour is covered in tests/record."""
from __future__ import annotations

import httpx

from app.main import app
from tests.api.questionnaire_http import submit


async def test_definition_submit_and_view_profile_v1_over_http(ctx, fake_llm):
    app.state.ctx = ctx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        definition = (await http.get("/api/questionnaire/definition")).json()
        sex = next(q for s in definition["sections"] for q in s["questions"] if q["id"] == "sex")
        assert sex["number"] == 3 and sex["required"] is False and sex["options"][0] == {"value": "female", "label": "Female"}

        patient = (await http.post("/api/patients", json={"label": "Demo patient A"})).json()["patient_id"]
        submitted = await http.post(f"/api/patients/{patient}/questionnaire", json={
            "definition_version": definition["version"], "respondent": "other",
            "answers": {"birth_month": "1958-03", "sex": "female", "postcode": "2031"}})
        assert submitted.status_code == 202
        body = submitted.json()
        assert body["document_hash"] and body["deduplicated"] is False
        state = (await http.get(f"/api/runs/{body['run_id']}")).json()["state"]
        assert state["phase"] == "committed" and state["version_number"] == 1

        version = (await http.get(f"/api/patients/{patient}/versions/{state['profile_version_id']}")).json()
        sex_fact = next(f for f in version["facts"] if f["subject"] == "sex assigned at birth")
        assert sex_fact["resource"] == "Patient"
        assert sex_fact["citation"]["label"] == "Patient-reported, intake questionnaire, Q3"
        assert sex_fact["citation"]["quote"] == "Female"
        assert version["current"]["sex assigned at birth"] == sex_fact["id"]

        bad = await http.post(f"/api/patients/{patient}/questionnaire", json={
            "definition_version": definition["version"], "respondent": "patient", "answers": {"sex": "x"}})
        assert bad.status_code == 422
        assert (await http.get(f"/api/patients/{patient}/versions/nope")).status_code == 404
    assert fake_llm.calls == []


async def test_the_served_definition_carries_the_free_text_questions_for_the_web_form():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        definition = (await http.get("/api/questionnaire/definition")).json()
    kinds = {q["id"]: (q["number"], q["kind"]) for s in definition["sections"] for q in s["questions"]}
    assert kinds["diagnosis"] == (6, "textarea") and kinds["diagnosis_when"] == (7, "text")
    assert kinds["treatments"] == (8, "textarea") and kinds["medicines"] == (9, "textarea")
    assert kinds["allergies"] == (11, "textarea") and kinds["other_illnesses"] == (12, "textarea")


async def test_a_submission_always_answers_with_its_document_and_run_even_when_the_run_is_rejected(ctx, fake_llm):
    # fake_llm has no script, so the free-text answer's Intake call fails and the run ends rejected
    app.state.ctx = ctx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        patient = (await http.post("/api/patients", json={"label": "Demo patient A"})).json()["patient_id"]

        accepted, state = await submit(http, patient, {"sex": "female", "medicines": "Tamoxifen 20 mg daily"})

        assert accepted["document_hash"] and accepted["run_id"] and accepted["return_token"]
        assert state["phase"] == "rejected" and "unavailable" in state["reason"]
        again, state = await submit(http, patient, {"sex": "female", "medicines": "Tamoxifen 20 mg daily"})
        assert again["document_hash"] == accepted["document_hash"] and again["run_id"] != accepted["run_id"]
