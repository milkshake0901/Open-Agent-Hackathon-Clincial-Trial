"""HTTP: the first submission carries the return token; GET /return/{token} opens that patient only."""
from __future__ import annotations

import httpx

from app.main import app


async def _submit(http, patient, answers):
    return (await http.post(f"/api/patients/{patient}/questionnaire", json={
        "definition_version": "1", "respondent": "patient", "answers": answers})).json()


async def test_first_submission_returns_a_link_that_reopens_only_that_patient(ctx):
    app.state.ctx = ctx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        a = (await http.post("/api/patients", json={"label": "Demo patient A"})).json()["patient_id"]
        b = (await http.post("/api/patients", json={"label": "Demo patient B"})).json()["patient_id"]
        first = await _submit(http, a, {"sex": "female", "postcode": "2031", "contact": "0412 345 678"})
        await _submit(http, b, {"sex": "male"})
        assert first["return_token"]
        again = await _submit(http, a, {"sex": "male"})
        assert again["return_token"] is None

        opened = await http.get(f"/api/return/{first['return_token']}")
        assert opened.status_code == 200
        body = opened.json()
        assert body == {"patient_id": a, "profile_version_id": again["profile_version_id"], "version_number": 2}
        assert "2031" not in opened.text and "0412" not in opened.text

        bad = await http.get("/api/return/not-a-token")
        assert bad.status_code == 404
        assert a not in bad.text and b not in bad.text and "Demo" not in bad.text
