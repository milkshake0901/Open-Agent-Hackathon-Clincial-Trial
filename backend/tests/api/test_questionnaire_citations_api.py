"""HTTP: a Criterion result citing a Patient-reported Fact opens the answer it quotes. Its Citation carries the
question's wording as the Respondent saw it and the whole answer, with where the quote sits in that answer, so the
Trials page can show the answer with the quoted part highlighted instead of a page image (#51)."""
from __future__ import annotations

import httpx

from app import trials
from app.llm.nightshift import FakeLLM
from app.main import app
from tests.api.questionnaire_http import submit
from tests.api.test_verdicts_api import SNAPSHOT, matcher_citing
from tests.condition_term import tick_condition_term


async def _cited(clean_db, respond, answers: dict, word: str, respondent: str = "patient") -> dict:
    """Submit `answers`, then the Citation of the one Criterion result whose text contains `word`."""
    from tests.conftest import make_ctx
    ctx = make_ctx(clean_db, FakeLLM(respond))
    await trials.load_snapshot(ctx, SNAPSHOT)
    app.state.ctx = ctx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        patient = (await http.post("/api/patients", json={"label": "Demo patient Q"})).json()["patient_id"]
        await tick_condition_term(ctx, patient)
        _, state = await submit(http, patient, answers, respondent)
        assert state["phase"] == "committed", state
        listed = (await http.get(f"/api/patients/{patient}/versions/{state['profile_version_id']}/verdicts")).json()
        result = next(r for r in listed["verdicts"][0]["results"] if word in r["text"])
        assert result["outcome"] == "met"
        return result["citation"]


async def test_a_citation_to_a_structured_answer_carries_the_question_and_the_whole_answer_it_quotes(clean_db):
    citation = await _cited(clean_db, matcher_citing({"ECOG": "daily activity"}),
                            {"birth_month": "1958-03", "daily_activity": "fully_active"}, "ECOG")
    assert citation["question"] == "Q13"
    assert citation["region"] is None
    assert citation["answer"] == {"wording": "Which best describes your usual day?",
                                  "text": "Fully active, doing everything as before the illness",
                                  "quote_start": 0, "quote_end": 52}


MEDICINES = "Osimertinib 80 mg daily\nPrednisolone 5 mg in the morning"


def intake_then_matcher(lane, system, user):
    """Intake drafts one Fact quoting part of the medicines answer; the Matcher cites it for the steroids criterion."""
    if lane == "fast":
        return {"facts": [{"resource": "MedicationStatement", "subject": "prednisolone", "value": "5 mg",
                           "observed_on": "2026-10-24", "page": 4, "quote": "prednisolone 5 mg", "question": "Q9"}]}
    return matcher_citing({"steroids": "prednisolone"})(lane, system, user)


async def test_a_citation_to_a_free_text_answer_locates_the_quoted_part_in_the_answer_someone_else_gave(clean_db):
    citation = await _cited(clean_db, intake_then_matcher, {"medicines": MEDICINES}, "steroids", respondent="other")
    assert citation["question"] == "Q9"
    assert citation["answer"] == {"wording": "What medicines do they take now?",
                                  "text": "Osimertinib 80 mg daily Prednisolone 5 mg in the morning",
                                  "quote_start": 24, "quote_end": 41}
