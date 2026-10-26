"""HTTP smoke test of adding Documents: each file answers 202 with its run, the ingest runs in the background, and the
run's state says which Profile version it made. Behaviour is covered in tests/record/test_adding_documents.py."""
from __future__ import annotations

from dataclasses import replace

import httpx

from app import record
from app.config import Settings
from app.main import app
from tests.conftest import ADMIN_DSN, make_ctx
from tests.fixtures.letters import recorded
from tests.record.test_adding_documents import (BLANK, BLOODS, BLOODS_FACTS, PARSE, REFERRAL, REFERRAL_FACTS,
                                                by_document)


async def test_several_added_documents_each_get_a_run_that_ends_in_its_own_profile_version(clean_db, tmp_path):
    ctx = make_ctx(clean_db, by_document(referral=REFERRAL_FACTS, Pathology=BLOODS_FACTS), parser=recorded(*PARSE))
    app.state.ctx = replace(ctx, settings=Settings(_env_file=None, pg_dsn=ADMIN_DSN, raw_documents_dir=str(tmp_path)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        patient = (await http.post("/api/patients", json={"label": "Demo patient H"})).json()["patient_id"]
        await http.post(f"/api/patients/{patient}/questionnaire", json={
            "definition_version": record.questionnaire_definition().version, "respondent": "patient",
            "answers": {"sex": "female"}})

        added = [await http.post(f"/api/patients/{patient}/documents",
                                   files={"file": (name, content, "application/pdf")})
                   for name, content in (("referral.pdf", REFERRAL), ("bloods.pdf", BLOODS))]
        assert [u.status_code for u in added] == [202, 202]
        assert [u.json()["deduplicated"] for u in added] == [False, False]

        runs = [(await http.get(f"/api/runs/{u.json()['run_id']}")).json() for u in added]
        assert [(r["kind"], r["state"]["phase"], r["state"]["version_number"]) for r in runs] == [
            ("ingest", "committed", 2), ("ingest", "committed", 3)]
        assert runs[0]["events"][0]["kind"] == "ingest.started"

        again = await http.post(f"/api/patients/{patient}/documents",
                                files={"file": ("referral-copy.pdf", REFERRAL, "application/pdf")})
        assert again.status_code == 202
        assert again.json() == {**added[0].json(), "deduplicated": True}

        scan = await http.post(f"/api/patients/{patient}/documents", files={"file": ("scan.pdf", BLANK)})
        assert scan.status_code == 422
        missing = await http.post("/api/patients/nope/documents", files={"file": ("a.pdf", REFERRAL)})
        assert missing.status_code == 404
        assert (await http.get("/api/runs/run_nope")).status_code == 404
