"""The trials facade's Australia-wide ingest (#21, ADR 0004), fed saved ClinicalTrials.gov v2 study pages (the
`GET /api/v2/studies` response body, one page per file) instead of the live API. Observed through trial, sites,
active_trials and criteria."""
from __future__ import annotations

import json

from app import trials

ELIGIBILITY = ("Inclusion Criteria:\n\n* Adults aged 18 years or older\n* ECOG Performance Status 0-1\n\n"
               "Exclusion Criteria:\n\n* Untreated CNS metastases")


def site(facility, city, country, status="RECRUITING"):
    return {"facility": facility, "city": city, "country": country, "status": status,
            "geoPoint": {"lat": -33.9, "lon": 151.2}}


def study(nct, *, status="RECRUITING", sites=(), eligibility=ELIGIBILITY, primary_completion=None, completion=None,
          last_update="2026-10-01", conditions=("Non-Small Cell Lung Cancer",)):
    """A ClinicalTrials.gov v2 study with just the fields the ingest reads."""
    dates = {**({"primaryCompletionDateStruct": {"date": primary_completion}} if primary_completion else {}),
             **({"completionDateStruct": {"date": completion}} if completion else {})}
    return {"protocolSection": {
        "identificationModule": {"nctId": nct, "briefTitle": f"Synthetic trial {nct}"},
        "statusModule": {"overallStatus": status, "lastUpdatePostDateStruct": {"date": last_update}, **dates},
        "conditionsModule": {"conditions": list(conditions)},
        "eligibilityModule": {"eligibilityCriteria": eligibility},
        "contactsLocationsModule": {"locations": list(sites)}}}


def save_pages(directory, *pages):
    """Each page is a list of studies, saved as a `GET /api/v2/studies` body; all but the last carry a nextPageToken."""
    directory.mkdir(parents=True, exist_ok=True)
    for i, studies in enumerate(pages, 1):
        body = {"studies": list(studies), **({"nextPageToken": f"token-{i}"} if i < len(pages) else {})}
        (directory / f"page-{i:03}.json").write_text(json.dumps({"fetched_at": "2026-10-25T00:00:00+00:00",
                                                                  "body": body}))
    return trials.SavedPages(directory)


AU = site("Royal Prince Alfred Hospital", "Camperdown", "Australia")


async def test_an_australian_open_trial_is_ingested_from_saved_pages(ctx, tmp_path):
    source = save_pages(tmp_path, [study("NCT00000001", sites=[AU])])

    report = await trials.ingest(ctx, source)

    assert report.new == ("NCT00000001",) and report.changed == () and report.unchanged == ()
    t = await trials.trial(ctx, trials.NctId("NCT00000001"))
    assert t.status == "RECRUITING" and t.title == "Synthetic trial NCT00000001"
    assert [t.nct_id for t in await trials.active_trials(ctx)] == ["NCT00000001"]
    assert await trials.sites(ctx, trials.NctId("NCT00000001")) == (trials.TrialSite(
        facility="Royal Prince Alfred Hospital", city="Camperdown", country="Australia", status="RECRUITING",
        lat=-33.9, lon=151.2),)


async def test_a_study_with_no_australian_site_is_not_stored(ctx, tmp_path):
    source = save_pages(tmp_path, [study("NCT00000002", sites=[site("Mayo Clinic", "Rochester", "United States")]),
                                   study("NCT00000003")])

    report = await trials.ingest(ctx, source)

    assert report.new == () and report.unchanged == ()
    assert await trials.trial(ctx, trials.NctId("NCT00000002")) is None
    assert await trials.trial(ctx, trials.NctId("NCT00000003")) is None


async def test_a_mixed_country_study_keeps_only_its_australian_sites(ctx, tmp_path):
    melbourne = site("Peter MacCallum Cancer Centre", "Melbourne", "Australia", status="NOT_YET_RECRUITING")
    source = save_pages(tmp_path, [study("NCT00000004", sites=[
        site("Mayo Clinic", "Rochester", "United States"), AU, site("Auckland City Hospital", "Auckland", "New Zealand"),
        melbourne])])

    await trials.ingest(ctx, source)

    kept = await trials.sites(ctx, trials.NctId("NCT00000004"))
    assert [(s.facility, s.status) for s in kept] == [("Royal Prince Alfred Hospital", "RECRUITING"),
                                                      ("Peter MacCallum Cancer Centre", "NOT_YET_RECRUITING")]


async def test_a_withdrawn_study_is_never_stored(ctx, tmp_path):
    source = save_pages(tmp_path, [study("NCT00000005", status="WITHDRAWN", sites=[AU])])

    report = await trials.ingest(ctx, source)

    assert report.new == ()
    assert await trials.trial(ctx, trials.NctId("NCT00000005")) is None


async def test_a_second_identical_run_reports_everything_unchanged_and_records_nothing(ctx, fake_llm, tmp_path):
    source = save_pages(tmp_path, [study("NCT00000001", sites=[AU])],
                        [study("NCT00000006", status="COMPLETED", sites=[AU])])
    await trials.ingest(ctx, source)
    events = len(ctx.wm.events())

    again = await trials.ingest(ctx, source)

    assert again.new == () and again.changed == () and again.unchanged == ("NCT00000001", "NCT00000006")
    assert len(ctx.wm.events()) == events
    assert fake_llm.calls == []


async def test_criteria_are_split_from_the_stored_eligibility_text_the_first_time_they_are_asked_for(ctx, fake_llm,
                                                                                                    tmp_path):
    source = save_pages(tmp_path, [study("NCT00000001", sites=[AU])])
    await trials.ingest(ctx, source)
    t = await trials.trial(ctx, trials.NctId("NCT00000001"))
    assert t.eligibility_text == ELIGIBILITY

    first = await trials.criteria(ctx, t.nct_id, for_agent=True)

    assert [(c.kind, c.text) for c in first] == [("inclusion", "Adults aged 18 years or older"),
                                                 ("inclusion", "ECOG Performance Status 0-1"),
                                                 ("exclusion", "Untreated CNS metastases")]
    assert [c.id for c in first] == [f"NCT00000001:{t.eligibility_hash[:8]}:{n}" for n in (1, 2, 3)]
    assert await trials.criteria(ctx, t.nct_id) == first
    assert fake_llm.calls == []
    again = await trials.ingest(ctx, source)
    assert again.unchanged == ("NCT00000001",)
    assert await trials.criteria(ctx, t.nct_id) == first


async def test_a_trial_that_closes_between_runs_is_reported_changed_and_is_no_longer_active(ctx, tmp_path):
    await trials.ingest(ctx, save_pages(tmp_path / "before", [study("NCT00000001", sites=[AU])]))

    later = await trials.ingest(ctx, save_pages(tmp_path / "after", [study("NCT00000001", status="COMPLETED",
                                                                           sites=[AU])]))

    assert later.changed == ("NCT00000001",) and later.new == () and later.unchanged == ()
    assert (await trials.trial(ctx, trials.NctId("NCT00000001"))).status == "COMPLETED"
    assert await trials.active_trials(ctx) == []


# The test clock (conftest NOW) is 2026-10-24, so the 15-year cutoff is 2011-10-24.

async def test_closed_trials_finished_within_15_years_are_kept_and_older_ones_are_not_stored(ctx, tmp_path):
    source = save_pages(tmp_path, [study("NCT00000014", status="COMPLETED", sites=[AU], primary_completion="2012-10"),
                                   study("NCT00000016", status="TERMINATED", sites=[AU], primary_completion="2010-10-01"),
                                   study("NCT00000001", sites=[AU], primary_completion="2001-01")])

    report = await trials.ingest(ctx, source)

    assert report.new == ("NCT00000014", "NCT00000001")
    assert report.closed == ("NCT00000014",) and report.dropped == ("NCT00000016",)
    assert await trials.trial(ctx, trials.NctId("NCT00000016")) is None
    assert [t.nct_id for t in await trials.closed_trials(ctx, "lung cancer")] == ["NCT00000014"]
    assert [t.nct_id for t in await trials.active_trials(ctx)] == ["NCT00000001"]


async def test_the_cutoff_falls_back_to_completion_then_last_update(ctx, tmp_path):
    source = save_pages(tmp_path, [
        study("NCT00000021", status="COMPLETED", sites=[AU], completion="2010-06", last_update="2025-01-01"),
        study("NCT00000022", status="UNKNOWN", sites=[AU], last_update="2009-03-01"),
        study("NCT00000023", status="SUSPENDED", sites=[AU], completion="2013-02-01", last_update="2008-01-01"),
        study("NCT00000024", status="ACTIVE_NOT_RECRUITING", sites=[AU], last_update="2024-05-01")])

    report = await trials.ingest(ctx, source)

    assert report.dropped == ("NCT00000021", "NCT00000022")
    assert report.closed == ("NCT00000023", "NCT00000024")


async def test_closed_trials_are_listed_for_a_condition_term_newest_first(ctx, tmp_path):
    source = save_pages(tmp_path, [
        study("NCT00000031", status="COMPLETED", sites=[AU], primary_completion="2015-04"),
        study("NCT00000032", status="TERMINATED", sites=[AU], primary_completion="2021-11-30"),
        study("NCT00000033", status="COMPLETED", sites=[AU], completion="2018-01"),
        study("NCT00000034", status="COMPLETED", sites=[AU], primary_completion="2023-01",
              conditions=("Breast Cancer",)),
        study("NCT00000035", sites=[AU])])

    await trials.ingest(ctx, source)

    closed = await trials.closed_trials(ctx, "non-small cell lung cancer")
    assert [(t.nct_id, t.closed_on) for t in closed] == [("NCT00000032", "2021-11-30"), ("NCT00000033", "2018-01-01"),
                                                         ("NCT00000031", "2015-04-01")]
    assert [t.nct_id for t in await trials.closed_trials(ctx, "breast cancer")] == ["NCT00000034"]


async def test_a_closed_trial_that_ages_past_15_years_is_dropped_on_a_later_run(ctx, tmp_path):
    from dataclasses import replace
    from datetime import datetime, timezone

    source = save_pages(tmp_path, [study("NCT00000041", status="COMPLETED", sites=[AU], primary_completion="2012-03"),
                                   study("NCT00000042", status="COMPLETED", sites=[AU], primary_completion="2020-03")])
    await trials.ingest(ctx, source)
    a_year_on = replace(ctx, now=lambda: datetime(2027, 10, 24, tzinfo=timezone.utc))

    later = await trials.ingest(a_year_on, source)

    assert later.dropped == ("NCT00000041",) and later.closed == ("NCT00000042",)
    assert later.unchanged == ("NCT00000042",) and later.new == () and later.changed == ()
    assert await trials.trial(ctx, trials.NctId("NCT00000041")) is None
    assert await trials.sites(ctx, trials.NctId("NCT00000041")) == ()
    assert [t.nct_id for t in await trials.closed_trials(ctx, "lung cancer")] == ["NCT00000042"]
    events = len(ctx.wm.events())
    again = await trials.ingest(a_year_on, source)
    assert again.dropped == ("NCT00000041",) and len(ctx.wm.events()) == events
