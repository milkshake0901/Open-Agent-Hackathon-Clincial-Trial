"""The trials facade over the saved ClinicalTrials.gov snapshot (data/trials_snapshot/), in place of a live sync."""
from __future__ import annotations

from pathlib import Path

from app import trials

SNAPSHOT = Path(__file__).resolve().parents[3] / "data" / "trials_snapshot"
NCT = trials.NctId("NCT07680790")


async def test_the_snapshot_trial_is_recorded_with_its_criteria_split_from_the_eligibility_text(ctx):
    report = await trials.load_snapshot(ctx, SNAPSHOT)

    assert report.new == (NCT,)
    t = await trials.trial(ctx, NCT)
    assert t.status == "RECRUITING" and t.conditions == ("Non-Small Cell Lung Cancer",)
    assert t.eligibility_hash.startswith("ced65c98")      # the hash the one-Trial Zetaris load computed
    assert [t.nct_id for t in await trials.active_trials(ctx)] == [NCT]
    criteria = await trials.criteria(ctx, NCT)
    # Ids match the Zetaris load; "Other protocol-defined inclusion/exclusion criteria apply." (8) names nothing
    # a Fact could decide, so it is not a Criterion.
    assert [c.id for c in criteria] == [f"NCT07680790:ced65c98:{n}" for n in range(1, 8)]
    assert [c.kind for c in criteria] == ["inclusion"] * 4 + ["exclusion"] * 3
    assert criteria[3].text == "Participants must have ECOG Performance Status 0-1"


async def test_loading_the_same_snapshot_again_changes_nothing(ctx):
    await trials.load_snapshot(ctx, SNAPSHOT)

    again = await trials.load_snapshot(ctx, SNAPSHOT)

    assert again.new == () and again.changed == () and again.unchanged == (NCT,)


async def test_the_snapshot_never_overwrites_trials_the_ingest_recorded(ctx, tmp_path):
    from tests.trials.test_ingest import AU, save_pages, study

    await trials.ingest(ctx, save_pages(tmp_path, [study(NCT, sites=[AU], conditions=("Lung Cancer",))]))

    report = await trials.load_snapshot(ctx, SNAPSHOT)

    assert report.fetched == 0 and report.new == report.changed == report.unchanged == ()
    assert (await trials.trial(ctx, NCT)).conditions == ("Lung Cancer",)
