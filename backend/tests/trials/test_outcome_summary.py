"""The trials facade's plain-language Outcome summary (#26): written by the model the first time a Closed trial's
Outcomes are opened, never at ingest, and cached by NCT id and Outcome content hash so unchanged Outcomes are never
summarised twice. The model is faked as the Re-scan tests do."""
from __future__ import annotations

from app import trials
from tests.trials.test_ingest import AU, save_pages, study
from tests.trials.test_outcomes import with_outcomes

NCT = trials.NctId("NCT00000011")
WRITTEN = "People who took Drug A lived about six months longer on average than people who took the placebo."


def summarising(fake, text=WRITTEN):
    def respond(lane, system, user):
        assert lane == "fast", f"unexpected {lane} call"
        return {"summary": text}
    fake.responder = respond


def completed(raw=None):
    return raw or with_outcomes(study(NCT, status="COMPLETED", primary_completion="2024-06", sites=[AU]))


async def test_a_closed_trials_outcomes_are_summarised_when_first_opened_and_not_at_ingest(ctx, fake_llm, tmp_path):
    summarising(fake_llm)
    await trials.ingest(ctx, save_pages(tmp_path, [completed()]))
    assert fake_llm.calls == []

    summary = await trials.outcome_summary(ctx, NCT)

    assert summary.text == WRITTEN
    [call] = fake_llm.calls
    assert "Overall survival" in call.user and "18.2" in call.user and "Placebo" in call.user


async def test_unchanged_outcomes_reuse_the_cached_summary_with_no_further_model_call(ctx, fake_llm, clean_db, tmp_path):
    from app.llm.nightshift import FakeLLM
    from tests.conftest import make_ctx

    summarising(fake_llm)
    await trials.ingest(ctx, save_pages(tmp_path / "first", [completed()]))
    first = await trials.outcome_summary(ctx, NCT)
    await trials.ingest(ctx, save_pages(tmp_path / "again", [completed()]))   # an identical re-ingest

    again = await trials.outcome_summary(ctx, NCT)
    later = make_ctx(clean_db, FakeLLM())   # a restarted app whose model would fail if called
    reopened = await trials.outcome_summary(later, NCT)

    assert again == first and reopened == first and reopened.text == WRITTEN
    assert len(fake_llm.calls) == 1


async def test_changed_outcomes_are_summarised_again_once_opened(ctx, fake_llm, tmp_path):
    summarising(fake_llm)
    await trials.ingest(ctx, save_pages(tmp_path / "before", [completed()]))
    before = await trials.outcome_summary(ctx, NCT)
    later = completed()
    later["resultsSection"]["outcomeMeasuresModule"]["outcomeMeasures"][0]["classes"][0]["categories"][0][
        "measurements"][0]["value"] = "19.0"   # a corrected result
    await trials.ingest(ctx, save_pages(tmp_path / "after", [later]))
    assert len(fake_llm.calls) == 1   # the ingest itself summarises nothing
    summarising(fake_llm, "People who took Drug A lived about seven months longer on average.")

    after = await trials.outcome_summary(ctx, NCT)

    assert after.text == "People who took Drug A lived about seven months longer on average."
    assert after.outcomes_hash != before.outcomes_hash
    assert len(fake_llm.calls) == 2 and "19.0" in fake_llm.calls[-1].user


async def test_a_lost_summary_cache_is_rebuilt_from_the_world_model_event_log(ctx, fake_llm, clean_db, tmp_path):
    from app import worldmodel

    summarising(fake_llm)
    await trials.ingest(ctx, save_pages(tmp_path, [completed()]))
    first = await trials.outcome_summary(ctx, NCT)
    await clean_db.execute("TRUNCATE outcome_summary")   # the projection is lost

    await worldmodel.rebuild_projections(ctx.writer, ctx.wm.namespace)

    assert await trials.outcome_summary(ctx, NCT) == first
    assert len(fake_llm.calls) == 1


async def test_an_unknown_trial_has_no_summary_and_asks_no_model(ctx, fake_llm):
    assert await trials.outcome_summary(ctx, trials.NctId("NCT09999999")) is None
    assert fake_llm.calls == []
