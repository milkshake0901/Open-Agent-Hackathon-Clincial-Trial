"""The trials facade's Condition labels (#32, ADR 0005): every label stored Trials use with Open and Closed counts, a
search by phrases, and the Open and Closed trials listing any of a set of labels. Fed saved pages (test_ingest)."""
from __future__ import annotations

from app import trials
from tests.trials.test_ingest import AU, save_pages, study

ACL_PAGES = [
    study("NCT00000101", sites=[AU], conditions=("Anterior Cruciate Ligament Rupture",)),
    study("NCT00000102", status="NOT_YET_RECRUITING", sites=[AU],
          conditions=("Anterior Cruciate Ligament Injury", "Knee Osteoarthritis")),
    study("NCT00000103", status="COMPLETED", sites=[AU], primary_completion="2022-06",
          conditions=("Anterior Cruciate Ligament Injuries",)),
    study("NCT00000104", status="TERMINATED", sites=[AU], primary_completion="2019-02",
          conditions=("anterior cruciate  ligament rupture",)),
    study("NCT00000105", sites=[AU], conditions=("Non-Small Cell Lung Cancer",))]


async def test_every_condition_label_is_listed_with_its_open_and_closed_counts(ctx, tmp_path):
    await trials.ingest(ctx, save_pages(tmp_path, ACL_PAGES))

    labels = await trials.condition_labels(ctx)

    assert labels == [trials.ConditionLabel("Anterior Cruciate Ligament Rupture", open=1, closed=1),
                      trials.ConditionLabel("Anterior Cruciate Ligament Injuries", open=0, closed=1),
                      trials.ConditionLabel("Anterior Cruciate Ligament Injury", open=1, closed=0),
                      trials.ConditionLabel("Knee Osteoarthritis", open=1, closed=0),
                      trials.ConditionLabel("Non-Small Cell Lung Cancer", open=1, closed=0)]
    assert labels[0].total == 2


async def test_a_search_returns_labels_containing_any_phrase_as_whole_words_most_used_first(ctx, tmp_path):
    await trials.ingest(ctx, save_pages(tmp_path, ACL_PAGES))

    found = await trials.search_condition_labels(ctx, ["cruciate LIGAMENT", "knee"], limit=3)

    assert [one.label for one in found] == ["Anterior Cruciate Ligament Rupture", "Anterior Cruciate Ligament Injuries",
                                            "Anterior Cruciate Ligament Injury"]
    assert [one.label for one in await trials.search_condition_labels(ctx, ["knee"], limit=10)] == [
        "Knee Osteoarthritis"]
    assert await trials.search_condition_labels(ctx, ["injur", "ligament cruciate", "lung-cancer x"], limit=10) == []
    assert [one.label for one in await trials.search_condition_labels(ctx, ["non small cell"], limit=10)] == [
        "Non-Small Cell Lung Cancer"]


ACL = ["Anterior Cruciate Ligament Rupture", "anterior  cruciate ligament INJURY", "Anterior Cruciate Ligament Injuries"]


async def test_the_open_and_closed_trials_listing_any_label_are_selected_ignoring_case_and_spacing(ctx, tmp_path):
    await trials.ingest(ctx, save_pages(tmp_path, ACL_PAGES))

    assert [t.nct_id for t in await trials.open_trials_with_labels(ctx, ACL)] == ["NCT00000101", "NCT00000102"]
    assert [t.nct_id for t in await trials.closed_trials_with_labels(ctx, ACL)] == ["NCT00000103", "NCT00000104"]
    assert [t.nct_id for t in await trials.open_trials_with_labels(ctx, ["knee osteoarthritis"])] == ["NCT00000102"]
    assert await trials.closed_trials_with_labels(ctx, ["Knee Osteoarthritis"]) == []
    assert await trials.open_trials_with_labels(ctx, ["Anterior Cruciate Ligament"]) == []
    assert await trials.open_trials_with_labels(ctx, []) == []


async def test_a_dropped_trial_is_never_selected_nor_counted(ctx, tmp_path):
    await trials.ingest(ctx, save_pages(tmp_path / "before", ACL_PAGES))
    await trials.ingest(ctx, save_pages(tmp_path / "after", [
        study("NCT00000101", status="WITHDRAWN", sites=[AU], conditions=("Anterior Cruciate Ligament Rupture",)),
        *ACL_PAGES[1:3],
        study("NCT00000104", status="TERMINATED", sites=[AU], primary_completion="2008-02",
              conditions=("anterior cruciate  ligament rupture",)),
        ACL_PAGES[4]]))

    assert [t.nct_id for t in await trials.open_trials_with_labels(ctx, ACL)] == ["NCT00000102"]
    assert [t.nct_id for t in await trials.closed_trials_with_labels(ctx, ACL)] == ["NCT00000103"]
    assert "Anterior Cruciate Ligament Rupture" not in [one.label for one in await trials.condition_labels(ctx)]
