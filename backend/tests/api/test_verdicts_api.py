"""HTTP smoke test: a committed questionnaire starts a Re-scan, and the ranked Verdicts come back with Citations
that point at the questionnaire question. Behaviour is covered in tests/matching; this only checks the wiring."""
from __future__ import annotations

from pathlib import Path

import httpx

from app import trials
from app.main import app
from app.llm.nightshift import FakeLLM

SNAPSHOT = Path(__file__).resolve().parents[3] / "data" / "trials_snapshot"


def matcher_citing(subject_by_text):
    """Cite the Fact whose subject is mapped from a word in the Criterion text; everything else unknown."""
    def respond(lane, system, user):
        if lane == "judge":
            return {"checks": [{"criterion_id": line.split()[1], "supported": True}
                               for line in user.splitlines() if line.startswith("CLAIM ")]}
        facts = {line.split(" | ")[1].split(":")[0]: line.split()[1]
                 for line in user.splitlines() if line.startswith("- fact:")}
        results = []
        for line in (line for line in user.splitlines() if line.startswith("- NCT")):
            cid = line.split()[1]
            word = next((w for w in subject_by_text if w in line), None)
            results.append({"criterion_id": cid, "outcome": "met" if word else "unknown",
                            "fact_id": facts[subject_by_text[word]] if word else None, "rationale": "per answers"})
        return {"results": results}
    return respond


async def test_a_committed_questionnaire_rescans_and_lists_ranked_cited_verdicts(clean_db):
    from tests.conftest import make_ctx
    fake = FakeLLM(matcher_citing({"ECOG": "daily activity"}))
    ctx = make_ctx(clean_db, fake)
    await trials.load_snapshot(ctx, SNAPSHOT)
    app.state.ctx = ctx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        definition = (await http.get("/api/questionnaire/definition")).json()
        patient = (await http.post("/api/patients", json={"label": "Demo patient A"})).json()["patient_id"]
        body = (await http.post(f"/api/patients/{patient}/questionnaire", json={
            "definition_version": definition["version"], "respondent": "patient",
            "answers": {"birth_month": "1958-03", "daily_activity": "fully_active"}})).json()
        assert body["outcome"] == "committed" and body["rescan"] == {"judged": 1, "failed": 0}
        vid = body["profile_version_id"]

        listed = (await http.get(f"/api/patients/{patient}/versions/{vid}/verdicts")).json()
        assert [(v["nct_id"], v["outcome"]) for v in listed["verdicts"]] == [("NCT07680790", "possible")]
        ecog = next(r for r in listed["verdicts"][0]["results"] if "ECOG" in r["text"])
        assert ecog["outcome"] == "met" and ecog["kind"] == "inclusion"
        assert ecog["citation"]["label"] == "Patient-reported, intake questionnaire, Q13"
        assert ecog["citation"]["question"] == "Q13"

        questions = (await http.get(f"/api/patients/{patient}/questions", params={"version": vid})).json()
        assert len(questions) == 6 and questions[0]["unblocks"] == ["NCT07680790"]

        again = (await http.post(f"/api/patients/{patient}/versions/{vid}/rescan")).json()
        assert again["judged"] == [] and again["skipped_existing"] == ["NCT07680790"]
        assert (await http.get(f"/api/patients/{patient}/versions/{vid}/verdicts/NCT07680790")).status_code == 200
        assert (await http.get(f"/api/patients/{patient}/versions/{vid}/verdicts/NCT0")).status_code == 404
