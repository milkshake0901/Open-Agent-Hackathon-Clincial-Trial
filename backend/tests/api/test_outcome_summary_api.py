"""HTTP: a Closed trial's plain-language Outcome summary (#26), written on first open and reused after. The model is
faked as the Re-scan tests do; caching behaviour is covered in tests/trials, this checks the wiring."""
from __future__ import annotations

import httpx

from app import trials
from app.main import app
from tests.trials.test_ingest import AU, save_pages, study
from tests.trials.test_outcome_summary import WRITTEN, summarising
from tests.trials.test_outcomes import with_outcomes


async def _client(ctx):
    app.state.ctx = ctx
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_opening_a_closed_trials_outcomes_returns_its_summary_once_written(ctx, fake_llm, tmp_path):
    summarising(fake_llm)
    await trials.ingest(ctx, save_pages(tmp_path, [with_outcomes(study("NCT00000011", status="COMPLETED",
                                                                       primary_completion="2024-06", sites=[AU]))]))
    async with await _client(ctx) as http:
        first = await http.get("/api/trials/NCT00000011/outcomes/summary")
        again = await http.get("/api/trials/NCT00000011/outcomes/summary")
        missing = await http.get("/api/trials/NCT09999999/outcomes/summary")

    assert first.status_code == 200 and first.json() == {"nct_id": "NCT00000011", "summary": WRITTEN}
    assert again.json() == first.json()
    assert len(fake_llm.calls) == 1
    assert missing.status_code == 404


async def test_a_summary_the_model_cannot_write_is_a_503_and_is_not_cached(ctx, fake_llm, tmp_path):
    await trials.ingest(ctx, save_pages(tmp_path, [with_outcomes(study("NCT00000011", status="COMPLETED",
                                                                       primary_completion="2024-06", sites=[AU]))]))
    async with await _client(ctx) as http:
        down = await http.get("/api/trials/NCT00000011/outcomes/summary")   # no response scripted: the model fails
        summarising(fake_llm)
        back = await http.get("/api/trials/NCT00000011/outcomes/summary")

    assert down.status_code == 503
    assert back.status_code == 200 and back.json()["summary"] == WRITTEN
