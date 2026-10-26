"""An unknown Criterion result shows the Context Facts it considered, each opening the letter at its Region (#50).

Through the HTTP API: the narrative letter is read into Facts (recorded Regions, scripted Intake), then a Re-scan
with a scripted Matcher that lists Context Facts on its unknown results: one real Fact of the Profile version and
one invented id. Only the real one is kept.
"""
from __future__ import annotations

import httpx
import pytest

from app import trials, worldmodel
from app.main import app
from tests.api.test_letter_citations_api import LETTER_FACTS, SNAPSHOT, add_letter, judging_the_letter, letter_ctx
from tests.condition_term import tick_condition_term
from tests.fixtures.letters import intake_reading

INVENTED = "fact:0000000000000000"


def considering_enantone(lane, system, user):
    """The letter judged as in #46, with every unknown result listing the letter's Enantone Fact and an invented id
    as the Facts it considered."""
    out = judging_the_letter(intake_reading(LETTER_FACTS))(lane, system, user)
    if lane != "deep":
        return out
    enantone = next(line.split()[1] for line in user.splitlines() if line.startswith("- fact:") and "| enantone:" in line)
    return {"results": [{**r, "context_fact_ids": [enantone, INVENTED]} if r["outcome"] == "unknown" else r
                        for r in out["results"]]}


async def rescanned_verdict(http, ctx) -> tuple[str, dict, dict]:
    """(letter hash, the Verdict as the API gives it, the letter's Regions by span_id)."""
    patient, letter, run = await add_letter(http)
    vid = run["state"]["profile_version_id"]
    await tick_condition_term(ctx, patient)
    await http.post(f"/api/patients/{patient}/versions/{vid}/rescan")
    [verdict] = (await http.get(f"/api/patients/{patient}/versions/{vid}/verdicts")).json()["verdicts"]
    regions = {r["span_id"]: r for r in (await http.get(f"/api/documents/{letter}/regions")).json()["regions"]}
    return letter, verdict, regions


async def test_an_unknown_result_keeps_only_the_context_facts_that_are_facts_of_the_profile_version(clean_db, tmp_path):
    ctx = letter_ctx(clean_db, tmp_path, considering_enantone)
    await trials.load_snapshot(ctx, SNAPSHOT)
    app.state.ctx = ctx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        letter, verdict, regions = await rescanned_verdict(http, ctx)

    unknowns = [r for r in verdict["results"] if r["outcome"] == "unknown"]
    assert unknowns
    for result in unknowns:
        assert result["citation"] is None, "an unknown result still cites no Fact"
        [context] = result["context_facts"]
        assert context["fact_id"] != INVENTED
        region = regions[context["region"]["span_id"]]
        assert (context["document_hash"], context["filename"], context["page"]) == (letter, "letter.pdf", region["page"])
        assert context["quote"] == "Enantone (leuprorelin) 3-monthly injections, started 1/3/23"
        assert context["label"] == f"page {region['page']}"
        assert context["region"] == pytest.approx(
            {"span_id": region["span_id"], "x0": region["x0"], "y0": region["y0"], "x1": region["x1"],
             "y1": region["y1"]})
    assert all(r["context_facts"] == [] for r in verdict["results"] if r["outcome"] != "unknown")


async def test_context_facts_are_rebuilt_from_the_world_model(clean_db, tmp_path):
    ctx = letter_ctx(clean_db, tmp_path, considering_enantone)
    await trials.load_snapshot(ctx, SNAPSHOT)
    app.state.ctx = ctx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        patient, letter, run = await add_letter(http)
        vid = run["state"]["profile_version_id"]
        await tick_condition_term(ctx, patient)
        await http.post(f"/api/patients/{patient}/versions/{vid}/rescan")
        before = (await http.get(f"/api/patients/{patient}/versions/{vid}/verdicts")).json()["verdicts"]

        await worldmodel.rebuild_projections(ctx.writer, ctx.wm.namespace)

        after = (await http.get(f"/api/patients/{patient}/versions/{vid}/verdicts")).json()["verdicts"]
    assert any(r["context_facts"] for r in before[0]["results"])
    assert after == before
