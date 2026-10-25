"""HTTP: an Enquiry for an Open trial (#28) or a Closed trial (#29). The Respondent gets an email body to edit, copy
and send themselves. An Open trial's asks about taking part: it cites the Verdict and turns unknown Criteria into
questions. A Closed trial's asks about its Outcomes or a follow-on study, and needs no Verdict. Either carries only the
clinical details they kept ticked and leaves their name and contact as placeholders. The model is faked; nothing is
stored and nothing is sent."""
from __future__ import annotations

import httpx
import pytest

from app import trials
from app.llm.nightshift import FakeLLM
from app.main import app
from tests.api.questionnaire_http import submit
from tests.api.test_verdicts_api import matcher_citing
from tests.trials.test_ingest import AU, save_pages, site, study, with_contacts
from tests.trials.test_outcomes import with_outcomes

NCT = "NCT00000007"
CLOSED = "NCT00000011"
ANSWERS = {"birth_month": "1958-03", "sex": "female", "daily_activity": "fully_active", "postcode": "2031",
           "contact": "respondent@example.com"}
DRAFTED = "I am writing to ask whether I could take part in this trial."


def melbourne(contacts=()):
    return {**site("Peter MacCallum Cancer Centre", "Melbourne", "Australia"), "geoPoint": {"lat": -37.8, "lon": 145.0},
            "contacts": list(contacts)}


def sydney(contacts=()):
    return {**AU, "contacts": list(contacts)}


SAM = {"name": "Sam Coordinator", "role": "CONTACT", "email": "sam@example.org"}
MEL = {"name": "Mel Nurse", "role": "CONTACT", "email": "mel@example.org"}


class Writer:
    """The fake model: the Matcher and Evaluator as in the Verdict tests, and the Enquiry writer on the fast lane."""

    def __init__(self):
        self.matcher = matcher_citing({"ECOG": "daily activity"})
        self.fake = FakeLLM(self.respond)

    def respond(self, lane, system, user):
        return {"body": DRAFTED} if lane == "fast" else self.matcher(lane, system, user)

    def enquiry_prompts(self) -> list[str]:
        return [c.system + "\n" + c.user for c in self.fake.calls if c.lane == "fast"]


@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def judged(clean_db, tmp_path, http, *studies):
    """A Respondent with Profile v1 judged against the ingested Trials; returns (patient, version, writer)."""
    from tests.conftest import make_ctx
    writer = Writer()
    ctx = make_ctx(clean_db, writer.fake)
    await trials.ingest(ctx, save_pages(tmp_path, list(studies)))
    app.state.ctx = ctx
    patient = (await http.post("/api/patients", json={"label": "Demo patient E"})).json()["patient_id"]
    _, state = await submit(http, patient, ANSWERS)
    assert state["phase"] == "committed"
    return patient, state["profile_version_id"], writer


def enquiry_url(patient, version, nct=NCT):
    return f"/api/patients/{patient}/versions/{version}/trials/{nct}/enquiry"


async def offered(http, patient, version, nct=NCT) -> list[dict]:
    """The clinical details the Respondent is shown before anything is drafted."""
    r = await http.get(enquiry_url(patient, version, nct))
    assert r.status_code == 200, r.text
    return r.json()["details"]


async def draft(http, patient, version, nct=NCT):
    """The Respondent opens the Enquiry, sees the details, keeps them all ticked and asks for the draft."""
    kept = [d["id"] for d in await offered(http, patient, version, nct)]
    return await http.post(enquiry_url(patient, version, nct), json={"include": kept})


async def test_an_open_trial_enquiry_asks_about_taking_part_and_goes_to_the_nearest_site_contact(clean_db, tmp_path, http):
    raw = with_contacts(study(NCT, sites=[melbourne([MEL]), sydney([SAM])]))
    patient, version, writer = await judged(clean_db, tmp_path, http, raw)
    r = await draft(http, patient, version)

    assert r.status_code == 200, r.text
    e = r.json()
    assert e["template"] == "open"
    assert e["recipient"] == {"name": "Sam Coordinator", "email": "sam@example.org", "kind": "site",
                              "facility": "Royal Prince Alfred Hospital"}
    assert e["sponsor"] == "Example Oncology Group"
    assert NCT in e["subject"]
    assert e["body"].startswith("Dear Sam Coordinator,")
    assert DRAFTED in e["body"]
    assert "[Your name]" in e["body"] and "[Your email or phone]" in e["body"]
    [prompt] = writer.enquiry_prompts()
    assert "taking part" in prompt
    assert "possible" in prompt                                     # the Verdict
    assert "Adults aged 18 years or older" in prompt                 # unknown Criteria, to become questions
    assert "Untreated CNS metastases" in prompt


async def test_the_respondent_sees_the_clinical_details_before_any_model_call_and_an_unticked_one_never_reaches_it(
        clean_db, tmp_path, http):
    patient, version, writer = await judged(clean_db, tmp_path, http, with_contacts(study(NCT, sites=[sydney([SAM])])))

    shown = await offered(http, patient, version)

    assert {(d["label"], d["text"], d["included"]) for d in shown} == {
        ("Age", "68 years", True), ("Sex assigned at birth", "Female", True),
        ("Daily activity", "Fully active, doing everything as before the illness", True)}
    assert writer.enquiry_prompts() == []
    kept = [d["id"] for d in shown if d["label"] != "Sex assigned at birth"]

    r = await http.post(enquiry_url(patient, version), json={"include": kept})

    assert r.status_code == 200, r.text
    assert [(d["label"], d["included"]) for d in r.json()["details"] if not d["included"]] == [
        ("Sex assigned at birth", False)]
    [prompt] = writer.enquiry_prompts()
    assert "Female" not in prompt and "Fully active, doing everything as before the illness" in prompt


async def test_nothing_is_drafted_until_the_respondent_has_confirmed_the_details(clean_db, tmp_path, http):
    patient, version, writer = await judged(clean_db, tmp_path, http, with_contacts(study(NCT, sites=[sydney([SAM])])))

    r = await http.post(enquiry_url(patient, version), json={})

    assert r.status_code == 422
    assert writer.enquiry_prompts() == []


async def test_the_model_sees_no_name_postcode_or_contact_and_nothing_is_stored(clean_db, tmp_path, http):
    patient, version, writer = await judged(clean_db, tmp_path, http, with_contacts(study(NCT, sites=[sydney([SAM])])))
    events = len(app.state.ctx.wm.events())
    tables = {t: await clean_db.fetchval(f"SELECT count(*) FROM {t}") for t in
              [r["tablename"] for r in await clean_db.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public'")]}

    e = (await draft(http, patient, version)).json()

    [prompt] = writer.enquiry_prompts()
    for private in ("Demo patient E", "respondent@example.com", "2031", "1958"):
        assert private not in prompt and private not in e["body"]
    assert e["body"].endswith("Kind regards,\n[Your name]\n[Your email or phone]\n")
    assert len(app.state.ctx.wm.events()) == events
    assert {t: await clean_db.fetchval(f"SELECT count(*) FROM {t}") for t in tables} == tables


async def test_with_no_site_email_the_enquiry_goes_to_the_central_contact(clean_db, tmp_path, http):
    no_email = {"name": "Front Desk", "role": "CONTACT", "phone": "02 0000 0000"}
    patient, version, _ = await judged(clean_db, tmp_path, http,
                                       with_contacts(study(NCT, sites=[sydney([no_email]), melbourne()])))

    e = (await draft(http, patient, version)).json()

    assert e["recipient"] == {"name": "Trial Contact Centre", "email": "trials@example.org", "kind": "central",
                              "facility": None}
    assert e["body"].startswith("Dear Trial Contact Centre,")


async def test_a_trial_with_no_email_still_gets_a_draft_with_a_blank_recipient_and_the_sponsor_named(
        clean_db, tmp_path, http):
    raw = study(NCT, sites=[sydney()])
    raw["protocolSection"]["sponsorCollaboratorsModule"] = {"leadSponsor": {"name": "Example Pharma"}}
    patient, version, _ = await judged(clean_db, tmp_path, http, raw)

    r = await draft(http, patient, version)

    assert r.status_code == 200, r.text
    e = r.json()
    assert e["recipient"] is None and e["sponsor"] == "Example Pharma"
    assert e["body"].startswith("Dear Example Pharma trial team,") and DRAFTED in e["body"]


async def test_no_enquiry_for_an_unknown_trial_or_another_patients_version(clean_db, tmp_path, http):
    patient, version, _ = await judged(clean_db, tmp_path, http, study(NCT, sites=[sydney()]))

    for url in (enquiry_url(patient, version, "NCT09999999"), enquiry_url("pt_someone_else", version)):
        assert (await http.get(url)).status_code == 404
        assert (await http.post(url, json={"include": []})).status_code == 404


def closed(nct=CLOSED, **kw):
    return with_outcomes(with_contacts(study(nct, status="COMPLETED", primary_completion="2024-06-30",
                                             sites=[sydney([SAM])], **kw)))


async def test_a_closed_trial_enquiry_asks_about_its_outcomes_or_a_follow_on_study_with_no_verdict_needed(
        clean_db, tmp_path, http):
    patient, version, writer = await judged(clean_db, tmp_path, http, closed())

    r = await draft(http, patient, version, CLOSED)

    assert r.status_code == 200, r.text
    e = r.json()
    assert e["template"] == "closed"
    assert CLOSED in e["subject"] and "results" in e["subject"].lower()
    assert DRAFTED in e["body"] and e["body"].endswith("Kind regards,\n[Your name]\n[Your email or phone]\n")
    [prompt] = writer.enquiry_prompts()
    assert "follow-on" in prompt and "taking part" not in prompt
    assert "Overall survival" in prompt and "Progression-free survival" in prompt   # planned outcome measures
    assert "18.2" in prompt and "Drug A" in prompt                                   # posted results
    assert "Overall survival in NSCLC" in prompt                                     # a linked publication
    assert "Fully active, doing everything as before the illness" in prompt
    for private in ("Demo patient E", "respondent@example.com", "2031", "1958"):
        assert private not in prompt and private not in e["body"]


async def test_a_trial_that_closed_after_it_was_judged_gets_a_closed_trial_enquiry(clean_db, tmp_path, http):
    patient, version, writer = await judged(clean_db, tmp_path / "open", http, study(NCT, sites=[sydney()]))
    await trials.ingest(app.state.ctx, save_pages(tmp_path / "closed", [study(NCT, status="COMPLETED",
                                                                            sites=[sydney()])]))

    r = await draft(http, patient, version)

    assert r.status_code == 200, r.text
    assert r.json()["template"] == "closed"
    [prompt] = writer.enquiry_prompts()
    assert "follow-on" in prompt and "possible" not in prompt     # its old Verdict is not cited


def officials(raw, *people):
    raw["protocolSection"]["contactsLocationsModule"]["overallOfficials"] = list(people)
    return raw


JANE = {"name": "Dr Jane Citizen", "affiliation": "Example University", "role": "PRINCIPAL_INVESTIGATOR",
        "email": "jane.citizen@example.edu"}
ALEX = {"name": "Alex Director", "affiliation": "Example Oncology Group", "role": "STUDY_DIRECTOR",
        "email": "alex@example.org"}


async def test_a_closed_trial_enquiry_goes_to_the_responsible_party_where_the_trial_lists_their_email(
        clean_db, tmp_path, http):
    patient, version, _ = await judged(clean_db, tmp_path, http, officials(closed(), ALEX, JANE))

    e = (await draft(http, patient, version, CLOSED)).json()

    assert e["recipient"] == {"name": "Dr Jane Citizen", "email": "jane.citizen@example.edu",
                              "kind": "responsible_party", "facility": None}
    assert e["body"].startswith("Dear Dr Jane Citizen,")


async def test_without_the_responsible_partys_email_a_closed_trial_enquiry_goes_to_an_overall_official(
        clean_db, tmp_path, http):
    no_email = {k: v for k, v in JANE.items() if k != "email"}
    patient, version, _ = await judged(clean_db, tmp_path, http, officials(closed(), no_email, ALEX))

    e = (await draft(http, patient, version, CLOSED)).json()

    assert e["recipient"] == {"name": "Alex Director", "email": "alex@example.org", "kind": "official",
                              "facility": None}
    assert e["body"].startswith("Dear Alex Director,")


async def test_a_closed_trial_with_no_email_still_gets_a_draft_with_a_blank_recipient_and_the_sponsor_named(
        clean_db, tmp_path, http):
    patient, version, _ = await judged(clean_db, tmp_path, http, closed())   # a central and a site contact have one

    e = (await draft(http, patient, version, CLOSED)).json()

    assert e["recipient"] is None and e["sponsor"] == "Example Oncology Group"
    assert e["body"].startswith("Dear Example Oncology Group trial team,") and DRAFTED in e["body"]


async def test_an_unticked_detail_never_reaches_the_model_for_a_closed_trial(clean_db, tmp_path, http):
    patient, version, writer = await judged(clean_db, tmp_path, http, closed())
    kept = [d["id"] for d in await offered(http, patient, version, CLOSED) if d["label"] != "Sex assigned at birth"]

    r = await http.post(enquiry_url(patient, version, CLOSED), json={"include": kept})

    assert [(d["label"], d["included"]) for d in r.json()["details"] if not d["included"]] == [
        ("Sex assigned at birth", False)]
    [prompt] = writer.enquiry_prompts()
    assert "Female" not in prompt


async def test_with_no_email_and_no_sponsor_named_the_enquiry_greets_the_trial_team(clean_db, tmp_path, http):
    patient, version, _ = await judged(clean_db, tmp_path, http, study(NCT, sites=[sydney()]))

    e = (await draft(http, patient, version)).json()

    assert e["recipient"] is None and e["sponsor"] == ""
    assert e["body"].startswith("Dear trial team,")


async def test_an_open_trial_with_no_verdict_yet_gets_an_open_enquiry_that_cites_none(clean_db, tmp_path, http):
    patient, version, writer = await judged(clean_db, tmp_path / "judged", http, study(NCT, sites=[sydney([SAM])]))
    later = "NCT00000009"   # ingested after the Re-scan, so not judged yet
    await trials.ingest(app.state.ctx, save_pages(tmp_path / "later", [study(NCT, sites=[sydney([SAM])]),
                                                                       study(later, sites=[sydney([SAM])])]))

    r = await draft(http, patient, version, later)

    assert r.status_code == 200, r.text
    assert r.json()["template"] == "open" and r.json()["recipient"]["email"] == "sam@example.org"
    [prompt] = writer.enquiry_prompts()
    assert "taking part" in prompt
    assert "Eligibility check (Verdict)" not in prompt and "Unknown criteria" not in prompt


async def test_what_the_model_is_given_is_read_through_the_agent_reader(clean_db, tmp_path, http):
    from dataclasses import replace
    from tests.conftest import Recording
    patient, version, _ = await judged(clean_db, tmp_path / "open", http, study(NCT, sites=[sydney([SAM])]))
    await trials.ingest(app.state.ctx, save_pages(tmp_path / "closed", [study(NCT, sites=[sydney([SAM])]), closed()]))
    agent = Recording(clean_db)
    app.state.ctx = replace(app.state.ctx, agent_reader=agent)

    assert (await draft(http, patient, version)).status_code == 200
    assert {"trial", "verdict", "criterion_result", "criterion", "fact"} <= agent.tables
    agent.tables.clear()
    assert (await draft(http, patient, version, CLOSED)).status_code == 200
    assert {"trial", "trial_outcome", "trial_publication", "fact"} <= agent.tables


async def test_a_drafted_enquiry_is_logged_without_the_respondents_or_the_contacts_details(clean_db, tmp_path, http):
    import json

    from app import logfile
    path = tmp_path / "trialmatch.jsonl"
    logfile.configure(path)
    try:
        patient, version, _ = await judged(clean_db, tmp_path / "pages", http,
                                           with_contacts(study(NCT, sites=[sydney([SAM])])))
        assert (await draft(http, patient, version)).status_code == 200
    finally:
        logfile.reset()

    text = path.read_text()
    [line] = [s for s in map(json.loads, text.splitlines()) if s["step"] == "enquiry.drafted"]
    assert line["nct_id"] == NCT and line["profile_version_id"] == version and line["template"] == "open"
    for private in ("respondent@example.com", "Demo patient E", "Sam Coordinator", "sam@example.org"):
        assert private not in text
