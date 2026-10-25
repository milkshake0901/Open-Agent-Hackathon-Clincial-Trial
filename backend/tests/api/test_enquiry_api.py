"""HTTP: an Enquiry for an Open trial (#28). The Respondent gets an email body to edit, copy and send themselves,
asking about taking part: it cites the Verdict, turns unknown Criteria into questions, carries only the clinical
details they kept ticked, and leaves their name and contact as placeholders. The model is faked; nothing is stored
and nothing is sent."""
from __future__ import annotations

import httpx
import pytest

from app import trials
from app.llm.nightshift import FakeLLM
from app.main import app
from tests.api.questionnaire_http import submit
from tests.api.test_verdicts_api import matcher_citing
from tests.trials.test_ingest import AU, save_pages, site, study, with_contacts

NCT = "NCT00000007"
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


async def test_an_open_trial_enquiry_asks_about_taking_part_and_goes_to_the_nearest_site_contact(clean_db, tmp_path, http):
    raw = with_contacts(study(NCT, sites=[melbourne([MEL]), sydney([SAM])]))
    patient, version, writer = await judged(clean_db, tmp_path, http, raw)
    r = await http.post(enquiry_url(patient, version), json={})

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


async def test_the_respondent_sees_the_clinical_details_and_an_unticked_one_never_reaches_the_model(
        clean_db, tmp_path, http):
    patient, version, writer = await judged(clean_db, tmp_path, http, with_contacts(study(NCT, sites=[sydney([SAM])])))

    offered = (await http.post(enquiry_url(patient, version), json={})).json()["details"]
    assert {(d["label"], d["text"], d["included"]) for d in offered} == {
        ("Age", "68 years", True), ("Sex assigned at birth", "Female", True),
        ("Daily activity", "Fully active, doing everything as before the illness", True)}
    sex = next(d["id"] for d in offered if d["label"] == "Sex assigned at birth")
    kept = [d["id"] for d in offered if d["id"] != sex]

    r = await http.post(enquiry_url(patient, version), json={"include": kept})

    assert r.status_code == 200, r.text
    assert [(d["label"], d["included"]) for d in r.json()["details"] if not d["included"]] == [
        ("Sex assigned at birth", False)]
    first, second = writer.enquiry_prompts()
    assert "Female" in first and "Female" not in second
    assert "Fully active, doing everything as before the illness" in second


async def test_the_model_sees_no_name_postcode_or_contact_and_nothing_is_stored(clean_db, tmp_path, http):
    patient, version, writer = await judged(clean_db, tmp_path, http, with_contacts(study(NCT, sites=[sydney([SAM])])))
    events = len(app.state.ctx.wm.events())
    tables = {t: await clean_db.fetchval(f"SELECT count(*) FROM {t}") for t in
              [r["tablename"] for r in await clean_db.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public'")]}

    e = (await http.post(enquiry_url(patient, version), json={})).json()

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

    e = (await http.post(enquiry_url(patient, version), json={})).json()

    assert e["recipient"] == {"name": "Trial Contact Centre", "email": "trials@example.org", "kind": "central",
                              "facility": None}
    assert e["body"].startswith("Dear Trial Contact Centre,")


async def test_a_trial_with_no_email_still_gets_a_draft_with_a_blank_recipient_and_the_sponsor_named(
        clean_db, tmp_path, http):
    raw = study(NCT, sites=[sydney()])
    raw["protocolSection"]["sponsorCollaboratorsModule"] = {"leadSponsor": {"name": "Example Pharma"}}
    patient, version, _ = await judged(clean_db, tmp_path, http, raw)

    r = await http.post(enquiry_url(patient, version), json={})

    assert r.status_code == 200, r.text
    e = r.json()
    assert e["recipient"] is None and e["sponsor"] == "Example Pharma"
    assert e["body"].startswith("Dear trial team,") and DRAFTED in e["body"]


async def test_no_enquiry_without_a_verdict_and_none_yet_for_a_closed_trial(clean_db, tmp_path, http):
    patient, version, _ = await judged(clean_db, tmp_path, http, study(NCT, sites=[sydney()]),
                                       study("NCT00000009", status="COMPLETED", sites=[sydney()]))

    assert (await http.post(enquiry_url(patient, version, "NCT09999999"), json={})).status_code == 404
    assert (await http.post(enquiry_url(patient, version, "NCT00000009"), json={})).status_code == 409
    assert (await http.post(enquiry_url("pt_someone_else", version), json={})).status_code == 404
