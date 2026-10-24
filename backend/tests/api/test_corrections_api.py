"""HTTP smoke test of editing answers: read the latest submission back, resubmit one change, view the diff.
Behaviour is covered through the record facade in tests/record/test_corrections.py."""
from __future__ import annotations

import httpx

from app.main import app

ANSWERS = {"birth_month": "1958-03", "sex": "female", "daily_activity": "light_activity"}


async def test_edit_answers_prefills_from_the_latest_submission_and_the_diff_shows_the_change(ctx):
    app.state.ctx = ctx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        version = (await http.get("/api/questionnaire/definition")).json()["version"]
        patient = (await http.post("/api/patients", json={"label": "Demo patient A"})).json()["patient_id"]
        assert (await http.get(f"/api/patients/{patient}/questionnaire")).status_code == 404

        v1 = (await http.post(f"/api/patients/{patient}/questionnaire", json={
            "definition_version": version, "respondent": "patient", "answers": {**ANSWERS, "postcode": "2031"}})).json()
        latest = (await http.get(f"/api/patients/{patient}/questionnaire")).json()
        assert latest == {"definition_version": version, "document_hash": v1["document_hash"],
                          "respondent": "patient", "answers": ANSWERS}

        v2 = (await http.post(f"/api/patients/{patient}/questionnaire", json={
            "definition_version": version, "respondent": "patient",
            "answers": {**latest["answers"], "daily_activity": "self_care"}})).json()
        assert v2["version_number"] == 2

        diff = await http.get(f"/api/patients/{patient}/versions/{v2['profile_version_id']}/diff",
                              params={"from": v1["profile_version_id"]})
        assert diff.status_code == 200
        body = diff.json()
        assert [f["subject"] for f in body["facts_added"]] == ["daily activity"]
        [changed] = body["subjects_changed"]
        assert (changed["subject"], changed["before"]["value"], changed["after"]["value"]) == (
            "daily activity", "light_activity", "self_care")
        assert changed["after"]["citation"]["label"] == "Patient-reported, intake questionnaire, Q13"
        assert (await http.get(f"/api/patients/{patient}/versions/{v2['profile_version_id']}/diff",
                               params={"from": "nope"})).status_code == 404
