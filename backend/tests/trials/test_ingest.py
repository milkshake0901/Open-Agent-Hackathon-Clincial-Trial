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


def study(nct, *, status="RECRUITING", sites=(), eligibility=ELIGIBILITY):
    """A ClinicalTrials.gov v2 study with just the fields the ingest reads."""
    return {"protocolSection": {
        "identificationModule": {"nctId": nct, "briefTitle": f"Synthetic trial {nct}"},
        "statusModule": {"overallStatus": status, "lastUpdatePostDateStruct": {"date": "2026-10-01"}},
        "conditionsModule": {"conditions": ["Non-Small Cell Lung Cancer"]},
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
