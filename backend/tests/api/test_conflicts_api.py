"""HTTP smoke test of Conflicts: a contradicting Document's run waits on the patient, its Conflicts show both sides
with their Documents and pages, and confirming commits the next version and re-scans it. Behaviour is covered in
tests/record/test_conflicts.py."""
from __future__ import annotations

from dataclasses import replace

import httpx

from app import record
from app.config import Settings
from app.main import app
from tests.conftest import ADMIN_DSN, make_ctx
from tests.record.test_conflicts import REFERRAL, REFERRAL_FACTS, parse
from tests.record.test_adding_documents import by_document


async def test_a_parked_document_shows_both_sides_and_confirming_commits_the_choice(clean_db, tmp_path):
    ctx = make_ctx(clean_db, by_document(referral=REFERRAL_FACTS), parser=parse())
    app.state.ctx = replace(ctx, settings=Settings(_env_file=None, pg_dsn=ADMIN_DSN, raw_documents_dir=str(tmp_path)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        patient = (await http.post("/api/patients", json={"label": "Demo patient K"})).json()["patient_id"]
        await http.post(f"/api/patients/{patient}/questionnaire", json={
            "definition_version": record.questionnaire_definition().version, "respondent": "patient",
            "answers": {"sex": "female", "daily_activity": "fully_active"}})
        run_id = (await http.post(f"/api/patients/{patient}/documents",
                                  files={"file": ("referral.pdf", REFERRAL, "application/pdf")})).json()["run_id"]

        assert (await http.get(f"/api/runs/{run_id}")).json()["state"]["phase"] == "awaiting_patient"
        conflicts = (await http.get(f"/api/runs/{run_id}/conflicts")).json()["conflicts"]
        [c] = conflicts
        assert (c["draft"]["filename"], c["draft"]["page"], c["draft"]["quote"], c["draft"]["value"]) == (
            "referral.pdf", 2, "ECOG 2 on 2026-10-20", "2")
        assert "ECOG 2 on 2026-10-20" in c["draft"]["page_text"]
        assert (c["accepted"]["label"], c["accepted"]["quote"], c["accepted"]["filename"]) == (
            "Patient-reported, intake questionnaire, Q13", "Fully active, doing everything as before the illness",
            "Intake questionnaire")
        assert c["draft"]["label"] == "referral.pdf, page 2"
        assert c["message"]

        bad = await http.post(f"/api/runs/{run_id}/confirm",
                              json={"resolutions": [{"conflict_id": "nope", "choice": "accept_draft"}]})
        assert bad.status_code == 422
        done = await http.post(f"/api/runs/{run_id}/confirm",
                               json={"resolutions": [{"conflict_id": c["id"], "choice": "accept_draft"}]})
        assert done.status_code == 202
        assert (done.json()["outcome"], done.json()["version_number"]) == ("committed", 2)
        assert done.json()["rescan"] is not None
        again = await http.post(f"/api/runs/{run_id}/confirm",
                                json={"resolutions": [{"conflict_id": c["id"], "choice": "accept_draft"}]})
        assert again.status_code == 409
        assert (await http.get("/api/runs/run_nope/conflicts")).status_code == 404
