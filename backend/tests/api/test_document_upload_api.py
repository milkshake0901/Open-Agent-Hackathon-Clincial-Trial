"""HTTP smoke test of uploads: each file answers 202 with its run, the ingest runs in the background, and the
run's state says which Profile version it made. Behaviour is covered in tests/record/test_document_upload.py."""
from __future__ import annotations

from dataclasses import replace

import httpx

from app import record
from app.config import Settings
from app.main import app
from tests.conftest import ADMIN_DSN, make_ctx
from tests.pdfs import make_pdf
from tests.record.test_document_upload import BLOODS, BLOODS_FACTS, REFERRAL, REFERRAL_FACTS, by_document


async def test_several_uploads_each_get_a_run_that_ends_in_its_own_profile_version(clean_db, tmp_path):
    ctx = make_ctx(clean_db, by_document(referral=REFERRAL_FACTS, Pathology=BLOODS_FACTS))
    app.state.ctx = replace(ctx, settings=Settings(_env_file=None, pg_dsn=ADMIN_DSN, raw_documents_dir=str(tmp_path)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        patient = (await http.post("/api/patients", json={"label": "Demo patient H"})).json()["patient_id"]
        await http.post(f"/api/patients/{patient}/questionnaire", json={
            "definition_version": record.questionnaire_definition().version, "respondent": "patient",
            "answers": {"sex": "female"}})

        uploads = [await http.post(f"/api/patients/{patient}/documents",
                                   files={"file": (name, content, "application/pdf")})
                   for name, content in (("referral.pdf", REFERRAL), ("bloods.pdf", BLOODS))]
        assert [u.status_code for u in uploads] == [202, 202]
        assert [u.json()["deduplicated"] for u in uploads] == [False, False]

        runs = [(await http.get(f"/api/runs/{u.json()['run_id']}")).json() for u in uploads]
        assert [(r["kind"], r["state"]["phase"], r["state"]["version_number"]) for r in runs] == [
            ("ingest", "committed", 2), ("ingest", "committed", 3)]
        assert runs[0]["events"][0]["kind"] == "ingest.started"

        again = await http.post(f"/api/patients/{patient}/documents",
                                files={"file": ("referral-copy.pdf", REFERRAL, "application/pdf")})
        assert again.status_code == 202
        assert again.json() == {**uploads[0].json(), "deduplicated": True}

        scan = await http.post(f"/api/patients/{patient}/documents", files={"file": ("scan.pdf", make_pdf(""))})
        assert scan.status_code == 422
        missing = await http.post("/api/patients/nope/documents", files={"file": ("a.pdf", REFERRAL)})
        assert missing.status_code == 404
        assert (await http.get("/api/runs/run_nope")).status_code == 404
