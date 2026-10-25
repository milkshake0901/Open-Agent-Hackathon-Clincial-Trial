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



async def test_a_trial_judged_while_open_keeps_its_verdict_once_closed_and_is_never_judged_again(ctx, fake_llm, tmp_path):
    from app import matching, record
    fake_llm.responder = lambda lane, system, user: {"results": [
        {"criterion_id": line.split()[1], "outcome": "unknown", "fact_id": None, "rationale": "not in the record"}
        for line in user.splitlines() if line.startswith("- NCT")]} if lane == "deep" else {"checks": []}
    await trials.ingest(ctx, save_pages(tmp_path / "before", [study("NCT00000001", sites=[AU])]))
    patient = await record.create_patient(ctx, "Demo patient")
    v1 = (await record.submit_questionnaire(ctx, patient, {"sex": "female"}, respondent="other")).version.id
    await matching.rescan(ctx, v1)
    judged = await matching.verdict(ctx, trials.NctId("NCT00000001"), v1)
    assert judged is not None

    await trials.ingest(ctx, save_pages(tmp_path / "after", [study("NCT00000001", status="COMPLETED", sites=[AU])]))

    assert await matching.verdict(ctx, trials.NctId("NCT00000001"), v1) == judged
    assert [t.nct_id for t in await trials.closed_trials(ctx, "lung cancer")] == ["NCT00000001"]
    calls = len(fake_llm.calls)
    again = await matching.rescan(ctx, v1)
    assert again.planned == () and again.judged == () and again.skipped_existing == ()
    assert len(fake_llm.calls) == calls

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
async def test_a_stored_trial_later_found_withdrawn_or_without_an_australian_site_is_dropped(ctx, fake_llm, tmp_path):
    from app import matching, record
    fake_llm.responder = lambda lane, system, user: {"results": [
        {"criterion_id": line.split()[1], "outcome": "unknown", "fact_id": None, "rationale": "not in the record"}
        for line in user.splitlines() if line.startswith("- NCT")]} if lane == "deep" else {"checks": []}
    await trials.ingest(ctx, save_pages(tmp_path / "before", [study("NCT00000051", sites=[AU]),
                                                              study("NCT00000052", sites=[AU])]))
    patient = await record.create_patient(ctx, "Demo patient")
    v1 = (await record.submit_questionnaire(ctx, patient, {"sex": "female"}, respondent="other")).version.id
    await matching.rescan(ctx, v1)
    judged = await matching.verdict(ctx, trials.NctId("NCT00000051"), v1)

    later = await trials.ingest(ctx, save_pages(tmp_path / "after", [
        study("NCT00000051", status="WITHDRAWN", sites=[AU]),
        study("NCT00000052", sites=[site("Mayo Clinic", "Rochester", "United States")])]))

    assert later.dropped == ("NCT00000051", "NCT00000052")
    assert await trials.trial(ctx, trials.NctId("NCT00000051")) is None
    assert await trials.sites(ctx, trials.NctId("NCT00000052")) == ()
    assert await trials.active_trials(ctx) == []
    assert await matching.verdicts_for_version(ctx, v1) == []
    kept = await matching.verdict(ctx, trials.NctId("NCT00000051"), v1)
    assert (kept.outcome, kept.results, kept.eligibility_hash) == (judged.outcome, judged.results,
                                                                   judged.eligibility_hash)
    calls = len(fake_llm.calls)
    again = await matching.rescan(ctx, v1)
    assert again.planned == () and len(fake_llm.calls) == calls


async def test_a_status_neither_open_nor_closed_is_not_stored_and_closed_counts_only_closed_trials(ctx, tmp_path):
    # Expanded access records (AVAILABLE, NO_LONGER_AVAILABLE, ...) are not Trials a patient can join or learn
    # Outcomes from; like a withdrawn study they are not stored (ADR 0004).
    await trials.ingest(ctx, save_pages(tmp_path / "before", [study("NCT00000062", sites=[AU])]))

    report = await trials.ingest(ctx, save_pages(tmp_path / "after", [
        study("NCT00000061", status="AVAILABLE", sites=[AU]),
        study("NCT00000062", status="NO_LONGER_AVAILABLE", sites=[AU]),
        study("NCT00000063", status="COMPLETED", sites=[AU], primary_completion="2020-01")]))

    assert report.closed == ("NCT00000063",)
    assert report.new == ("NCT00000063",) and report.dropped == ("NCT00000062",)
    assert await trials.trial(ctx, trials.NctId("NCT00000061")) is None
    assert await trials.trial(ctx, trials.NctId("NCT00000062")) is None
    assert [t.nct_id for t in await trials.closed_trials(ctx, "lung cancer")] == list(report.closed)


def with_contacts(raw):
    """The study with the contact fields ClinicalTrials.gov lists (#27): central contacts, overall officials, lead
    sponsor and responsible party."""
    p = raw["protocolSection"]
    p["contactsLocationsModule"].update({
        "centralContacts": [{"name": "Trial Contact Centre", "role": "CONTACT", "phone": "1800 000 000",
                             "email": "trials@example.org"}],
        "overallOfficials": [{"name": "Dr Jane Citizen", "affiliation": "Example University",
                              "role": "PRINCIPAL_INVESTIGATOR"}]})
    p["sponsorCollaboratorsModule"] = {
        "leadSponsor": {"name": "Example Oncology Group", "class": "OTHER"},
        "responsibleParty": {"type": "PRINCIPAL_INVESTIGATOR", "investigatorFullName": "Jane Citizen",
                             "investigatorTitle": "Professor", "investigatorAffiliation": "Example University"}}
    return raw


async def test_a_trials_contacts_are_stored_with_its_australian_sites_contacts(ctx, tmp_path):
    sydney = {**AU, "contacts": [{"name": "Sam Coordinator", "role": "CONTACT", "phone": "+61 2 0000 0000",
                                  "email": "sam@example.org"}]}
    source = save_pages(tmp_path, [with_contacts(study("NCT00000007", sites=[
        site("Mayo Clinic", "Rochester", "United States"), sydney]))])

    await trials.ingest(ctx, source)

    c = await trials.contacts(ctx, trials.NctId("NCT00000007"))
    assert c.sponsor == "Example Oncology Group"
    assert c.page_url == "https://clinicaltrials.gov/study/NCT00000007"
    assert c.central == (trials.Contact(name="Trial Contact Centre", role="CONTACT", email="trials@example.org",
                                        phone="1800 000 000"),)
    assert c.officials == (trials.Contact(name="Dr Jane Citizen", role="PRINCIPAL_INVESTIGATOR",
                                          affiliation="Example University"),)
    assert c.responsible_party == trials.Contact(name="Jane Citizen", role="PRINCIPAL_INVESTIGATOR",
                                                 title="Professor", affiliation="Example University")
    [kept] = await trials.sites(ctx, trials.NctId("NCT00000007"))
    assert kept.facility == "Royal Prince Alfred Hospital"
    assert kept.contacts == (trials.Contact(name="Sam Coordinator", role="CONTACT", email="sam@example.org",
                                            phone="+61 2 0000 0000"),)


async def test_a_sponsor_responsible_party_is_named_by_the_sponsor_and_missing_contacts_are_empty(ctx, tmp_path):
    raw = study("NCT00000008", sites=[AU])
    raw["protocolSection"]["sponsorCollaboratorsModule"] = {"leadSponsor": {"name": "Example Pharma"},
                                                            "responsibleParty": {"type": "SPONSOR"}}
    await trials.ingest(ctx, save_pages(tmp_path, [raw]))

    c = await trials.contacts(ctx, trials.NctId("NCT00000008"))
    assert c.responsible_party == trials.Contact(name="Example Pharma", role="SPONSOR")
    assert c.central == () and c.officials == ()
    assert (await trials.sites(ctx, trials.NctId("NCT00000008")))[0].contacts == ()
    assert await trials.contacts(ctx, trials.NctId("NCT09999999")) is None


async def test_changed_contacts_replace_the_stored_ones(ctx, tmp_path):
    await trials.ingest(ctx, save_pages(tmp_path / "before", [with_contacts(study("NCT00000007", sites=[AU]))]))
    later = study("NCT00000007", sites=[AU])
    later["protocolSection"]["contactsLocationsModule"]["centralContacts"] = [{"name": "New Desk", "role": "CONTACT"}]

    await trials.ingest(ctx, save_pages(tmp_path / "after", [later]))

    c = await trials.contacts(ctx, trials.NctId("NCT00000007"))
    assert c.central == (trials.Contact(name="New Desk", role="CONTACT"),)
    assert c.officials == () and c.sponsor == "" and c.responsible_party is None


async def test_an_ingest_run_writes_its_start_and_report_to_the_log_file(ctx, tmp_path):
    from app import logfile
    source = save_pages(tmp_path / "pages", [study("NCT00000001", sites=[AU]),
                                             study("NCT00000009", status="COMPLETED", completion="2025-01", sites=[AU])])
    path = tmp_path / "trialmatch.jsonl"
    logfile.configure(path)
    try:
        await trials.ingest(ctx, source)
    finally:
        logfile.reset()

    steps = [json.loads(x) for x in path.read_text().splitlines()]
    started = next(s for s in steps if s["step"] == "trials.ingest.started")
    finished = next(s for s in steps if s["step"] == "trials.ingest.finished")
    assert started["source"] == "saved_pages"
    assert finished["fetched"] == 2 and finished["new"] == ["NCT00000001", "NCT00000009"]
    assert finished["closed"] == ["NCT00000009"] and finished["unchanged"] == 0 and finished["dropped"] == []
