"""HTTP smoke test: a committed questionnaire starts a Re-scan, and the ranked Verdicts come back with Citations
that point at the questionnaire question. Behaviour is covered in tests/matching; this only checks the wiring."""
from __future__ import annotations

from pathlib import Path

import httpx

from app import trials
from app.main import app
from tests.api.questionnaire_http import submit
from tests.condition_term import tick_condition_term
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
            word = next((w for w in subject_by_text if w in line and subject_by_text[w] in facts), None)
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
        patient = (await http.post("/api/patients", json={"label": "Demo patient A"})).json()["patient_id"]
        await tick_condition_term(ctx, patient)
        _, state = await submit(http, patient, {"birth_month": "1958-03", "daily_activity": "fully_active"})
        assert state["phase"] == "committed"
        vid = state["profile_version_id"]

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


async def test_an_added_document_that_commits_a_new_version_rescans_it(clean_db, tmp_path):
    from dataclasses import replace

    from app import record
    from app.config import Settings
    from tests.conftest import ADMIN_DSN, make_ctx
    from tests.fixtures.letters import recorded
    from tests.record.test_adding_documents import PARSE, REFERRAL, REFERRAL_FACTS

    judge = matcher_citing({})

    def respond(lane, system, user):
        return {"facts": REFERRAL_FACTS} if lane == "fast" else judge(lane, system, user)
    ctx = make_ctx(clean_db, FakeLLM(respond), parser=recorded(*PARSE))
    ctx = replace(ctx, settings=Settings(_env_file=None, pg_dsn=ADMIN_DSN, raw_documents_dir=str(tmp_path)))
    await trials.load_snapshot(ctx, SNAPSHOT)
    app.state.ctx = ctx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        patient = (await http.post("/api/patients", json={"label": "Demo patient U"})).json()["patient_id"]
        await tick_condition_term(ctx, patient)
        await http.post(f"/api/patients/{patient}/questionnaire", json={
            "definition_version": record.questionnaire_definition().version, "respondent": "patient",
            "answers": {"sex": "female"}})

        added = await http.post(f"/api/patients/{patient}/documents",
                                 files={"file": ("referral.pdf", REFERRAL, "application/pdf")})
        run = (await http.get(f"/api/runs/{added.json()['run_id']}")).json()
        assert run["state"]["version_number"] == 2
        v2 = run["state"]["profile_version_id"]

        listed = (await http.get(f"/api/patients/{patient}/versions/{v2}/verdicts")).json()
        assert [v["nct_id"] for v in listed["verdicts"]] == ["NCT07680790"]


async def test_the_version_diff_lists_the_verdicts_that_changed_and_the_criteria_that_moved(clean_db):
    from tests.conftest import make_ctx
    ctx = make_ctx(clean_db, FakeLLM(matcher_citing({"ECOG": "daily activity"})))
    await trials.load_snapshot(ctx, SNAPSHOT)
    app.state.ctx = ctx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        patient = (await http.post("/api/patients", json={"label": "Demo patient D"})).json()["patient_id"]
        await tick_condition_term(ctx, patient)
        v1 = (await submit(http, patient, {"birth_month": "1958-03"}))[1]["profile_version_id"]
        v2 = (await submit(http, patient, {"birth_month": "1958-03", "daily_activity": "fully_active"}))[1][
            "profile_version_id"]

        diff = (await http.get(f"/api/patients/{patient}/versions/{v2}/diff", params={"from": v1})).json()

        [changed] = diff["verdicts_changed"]
        assert (changed["nct_id"], changed["outcome_from"], changed["outcome_to"]) == ("NCT07680790", "possible", "possible")
        [moved] = changed["criteria_changed"]
        assert "ECOG" in moved["text"] and (moved["outcome_from"], moved["outcome_to"]) == ("unknown", "met")
        assert moved["citation"]["label"] == "Patient-reported, intake questionnaire, Q13"


async def test_respondent_questions_are_served_apart_from_doctor_questions(clean_db):
    from tests.conftest import make_ctx
    doctor_model = matcher_citing({})

    def respond(lane, system, user):
        out = doctor_model(lane, system, user)
        if lane == "deep":    # the ECOG Criterion turns on the daily-activity answer, which was skipped
            for r, line in zip(out["results"], (l for l in user.splitlines() if l.startswith("- NCT"))):
                r["ask"] = "Q13" if "ECOG" in line else None
        return out
    ctx = make_ctx(clean_db, FakeLLM(respond))
    await trials.load_snapshot(ctx, SNAPSHOT)
    app.state.ctx = ctx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        patient = (await http.post("/api/patients", json={"label": "Demo patient Q"})).json()["patient_id"]
        await tick_condition_term(ctx, patient)
        vid = (await submit(http, patient, {"birth_month": "1958-03"}))[1]["profile_version_id"]

        asked = (await http.get(f"/api/patients/{patient}/respondent-questions", params={"version": vid})).json()
        doctor = (await http.get(f"/api/patients/{patient}/questions", params={"version": vid})).json()
        verdict = (await http.get(f"/api/patients/{patient}/versions/{vid}/verdicts/NCT07680790")).json()

        assert [(q["question"], q["question_id"], q["unblocks"]) for q in asked] == [
            ("Q13", "daily_activity", ["NCT07680790"])]
        assert len(doctor) == 6 and not any("ECOG" in q["subject"] for q in doctor)
        assert [q["question"] for q in verdict["respondent_questions"]] == ["Q13"]
        assert (await http.get(f"/api/patients/{patient}/respondent-questions",
                               params={"version": "snap:nope"})).status_code == 404


async def test_listed_verdicts_carry_site_lines_and_the_further_away_flag_but_never_the_postcode(clean_db):
    from tests.conftest import make_ctx
    ctx = make_ctx(clean_db, FakeLLM(matcher_citing({"ECOG": "daily activity"})))
    await trials.load_snapshot(ctx, SNAPSHOT)
    app.state.ctx = ctx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        patient = (await http.post("/api/patients", json={"label": "Demo patient W"})).json()["patient_id"]
        await tick_condition_term(ctx, patient)
        _, state = await submit(http, patient, {"birth_month": "1958-03", "postcode": "2145", "max_travel_km": "25"})

        listed = await http.get(f"/api/patients/{patient}/versions/{state['profile_version_id']}/verdicts")

    [v] = listed.json()["verdicts"]
    assert v["sites"][0] == {"name": "Local Institution - 0439, Westmead, Australia", "status": "not yet recruiting",
                             "km": 1}
    assert v["nearest_site"]["status"] == "recruiting" and v["nearest_site"]["km"] > 5000
    assert v["further_away"] is True
    assert "2145" not in listed.text


async def test_without_a_condition_term_a_committed_questionnaire_judges_nothing_and_the_list_names_no_labels(
        clean_db):
    from tests.conftest import make_ctx
    fake = FakeLLM(matcher_citing({"ECOG": "daily activity"}))
    ctx = make_ctx(clean_db, fake)
    await trials.load_snapshot(ctx, SNAPSHOT)
    app.state.ctx = ctx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        patient = (await http.post("/api/patients", json={"label": "Demo patient N"})).json()["patient_id"]
        _, state = await submit(http, patient, {"birth_month": "1958-03", "daily_activity": "fully_active"})
        vid = state["profile_version_id"]

        listed = (await http.get(f"/api/patients/{patient}/versions/{vid}/verdicts")).json()
        assert state["phase"] == "committed" and fake.calls == []
        assert listed["condition_term"] is None and listed["verdicts"] == []

        await tick_condition_term(ctx, patient, ["non-small cell lung cancer"])
        rescanned = (await http.post(f"/api/patients/{patient}/versions/{vid}/rescan")).json()
        listed = (await http.get(f"/api/patients/{patient}/versions/{vid}/verdicts")).json()

    assert rescanned["judged"] == ["NCT07680790"]
    assert listed["condition_term"] == ["Non-Small Cell Lung Cancer"]
    assert [v["nct_id"] for v in listed["verdicts"]] == ["NCT07680790"]
