"""HTTP test of uploading a letter with Nemotron Parse replaced through Ctx by recorded Regions: no network call."""
from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from app.config import Settings
from app.main import app
from tests.conftest import ADMIN_DSN, make_ctx
from tests.fixtures.letters import NARRATIVE_LETTER, STRUCTURED_REPORT, RecordedParse, letter_pdf


@pytest.mark.parametrize("recording", [NARRATIVE_LETTER, STRUCTURED_REPORT], ids=["narrative", "structured"])
async def test_a_letter_uploads_through_the_recorded_parse_on_ctx(clean_db, tmp_path, recording):
    parser = RecordedParse(recording)
    ctx = make_ctx(clean_db, parser=parser)
    app.state.ctx = replace(ctx, settings=Settings(_env_file=None, pg_dsn=ADMIN_DSN, raw_documents_dir=str(tmp_path)))
    content = letter_pdf(recording)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        uploaded = await http.post("/api/referrals", files={"file": ("letter.pdf", content, "application/pdf")})
        assert uploaded.status_code == 200
        letter = uploaded.json()
        assert parser.reads == [content]

        listed = (await http.get("/api/referrals")).json()["letters"]
        assert [entry["document_hash"] for entry in listed] == [letter["document_hash"]]

        last = len(recording.pages)
        image = await http.get(f"/api/documents/{letter['document_hash']}/pages/{last}/image")
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"

        again = await http.post("/api/referrals", files={"file": ("letter.pdf", content, "application/pdf")})
        assert again.json()["document_hash"] == letter["document_hash"]
        assert parser.reads == [content]   # the stored Regions are reused, not read again
