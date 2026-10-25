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
