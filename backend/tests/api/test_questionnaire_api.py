"""HTTP smoke test of the tracer: definition → patient → submit → Profile v1 with questionnaire Citations.
The routes only call the record facade; behaviour is covered in tests/record."""
from __future__ import annotations

import httpx

from app.main import app


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
        assert body["outcome"] == "committed" and body["version_number"] == 1

        version = (await http.get(f"/api/patients/{patient}/versions/{body['profile_version_id']}")).json()
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
