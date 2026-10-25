"""HTTP: Closed trials for the patient's Condition term (#23, ADR 0004), listed apart from Verdicts, newest first and
never judged. The ingest is fed saved study pages; the model is faked as in the Re-scan tests."""
from __future__ import annotations

import httpx

from app import trials
from app.llm.nightshift import FakeLLM
from app.main import app
from tests.api.questionnaire_http import submit
from tests.trials.test_ingest import AU, save_pages, study

DIAGNOSIS = "lung cancer, the non small cell kind"


def respond(lane, system, user):
    if lane == "fast" and "condition term" in system:
        return {"term": "non-small cell lung cancer", "confidence": 0.9}
    if lane == "fast":
        return {"facts": [{"resource": "Condition", "subject": "lung cancer", "value": "non-small cell",
                           "observed_on": "2026-10-24", "page": 2, "quote": DIAGNOSIS, "question": "Q6"}]}
    if lane == "deep":
        return {"results": [{"criterion_id": line.split()[1], "outcome": "unknown", "fact_id": None, "rationale": "x"}
                            for line in user.splitlines() if line.startswith("- NCT")]}
    return {"checks": []}


async def test_closed_trials_for_the_condition_term_are_listed_newest_first_and_never_judged(clean_db, tmp_path):
    from tests.conftest import make_ctx
    fake = FakeLLM(respond)
    ctx = make_ctx(clean_db, fake)
    await trials.ingest(ctx, save_pages(tmp_path, [
        study("NCT00000001", sites=[AU]),
        study("NCT00000051", status="COMPLETED", sites=[AU], primary_completion="2016-05"),
        study("NCT00000052", status="TERMINATED", sites=[AU], primary_completion="2022-08-15"),
        study("NCT00000053", status="COMPLETED", sites=[AU], primary_completion="2010-01"),
        study("NCT00000054", status="COMPLETED", sites=[AU], primary_completion="2023-01",
              conditions=("Breast Cancer",))]))
    app.state.ctx = ctx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        patient = (await http.post("/api/patients", json={"label": "Demo patient C"})).json()["patient_id"]
        _, state = await submit(http, patient, {"diagnosis": DIAGNOSIS})
        vid = state["profile_version_id"]
        url = f"/api/patients/{patient}/closed-trials"
        before = (await http.get(url)).json()
        assert before == {"condition_term": None, "trials": []}

        check = (await http.post(f"/api/patients/{patient}/questionnaire/diagnosis-check", json={})).json()
        await http.post(f"/api/patients/{patient}/questionnaire/diagnosis-check/{check['id']}", json={"answer": "yes"})

        listed = (await http.get(url)).json()
        assert listed["condition_term"] == "non-small cell lung cancer"
        assert [(t["nct_id"], t["status"], t["closed_on"]) for t in listed["trials"]] == [
            ("NCT00000052", "TERMINATED", "2022-08-15"), ("NCT00000051", "COMPLETED", "2016-05-01")]
        first = listed["trials"][0]
        assert first["title"] == "Synthetic trial NCT00000052"
        assert first["url"] == "https://clinicaltrials.gov/study/NCT00000052"
        assert not {"outcome", "verdict", "results"} & first.keys()

        rescan = (await http.post(f"/api/patients/{patient}/versions/{vid}/rescan")).json()
        verdicts = (await http.get(f"/api/patients/{patient}/versions/{vid}/verdicts")).json()["verdicts"]
        assert rescan["judged"] + rescan["skipped_existing"] == ["NCT00000001"]
        assert [v["nct_id"] for v in verdicts] == ["NCT00000001"]
        assert not any("NCT0000005" in c.user for c in fake.calls)
