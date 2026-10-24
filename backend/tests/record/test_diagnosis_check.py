"""Seam 1 (spec #5): the record facade, for diagnosis normalisation (#14). A model (scripted fake) proposes a
condition term for the free-text diagnosis; the Respondent answers yes / no / not sure. Observed through
check_diagnosis, answer_diagnosis_check, diagnosis and the prompts the fake captured."""
from __future__ import annotations

import pytest

from app import record
from app.llm.nightshift import FakeLLM

DIAGNOSIS = "lung cancer, the non small cell kind"
INTAKE_FACTS = [{"resource": "Condition", "subject": "lung cancer", "value": "non-small cell", "observed_on": "2026-10-24",
                 "page": 2, "quote": DIAGNOSIS, "question": "Q6"}]


def fake_model(*terms):
    """Intake answers with INTAKE_FACTS; each diagnosis-term call answers with the next (term, confidence)."""
    replies = list(terms)

    def respond(lane, system, user):
        if "condition term" in system:
            term, confidence = replies.pop(0)
            return {"term": term, "confidence": confidence}
        return {"facts": INTAKE_FACTS}
    return FakeLLM(respond)


async def _submitted(clean_db, *terms):
    from tests.conftest import make_ctx
    fake = fake_model(*terms)
    ctx = make_ctx(clean_db, fake)
    patient = await record.create_patient(ctx, "Demo patient D")
    outcome = await record.submit_questionnaire(ctx, patient, {"diagnosis": DIAGNOSIS, "postcode": "2031"}, "patient")
    assert isinstance(outcome, record.Committed)
    return ctx, fake, patient, outcome.version


async def test_a_confirmed_term_becomes_the_patients_condition_and_the_free_text_stays_the_quote(clean_db):
    ctx, fake, patient, version = await _submitted(clean_db, ("non-small cell lung cancer", 0.92))

    check = await record.check_diagnosis(ctx, patient)

    assert check.text == DIAGNOSIS and check.suggested_term == "non-small cell lung cancer"
    assert check.status == "proposed" and not check.needs_gp
    prompt = fake.calls[-1]
    assert prompt.lane == "fast" and DIAGNOSIS in prompt.user and "2031" not in prompt.user
    assert await record.diagnosis(ctx, patient) is None      # nothing holds until the Respondent answers

    answered = await record.answer_diagnosis_check(ctx, patient, check.id, "yes")

    assert answered.status == "confirmed" and answered.condition_term == "non-small cell lung cancer"
    assert (await record.diagnosis(ctx, patient)).condition_term == "non-small cell lung cancer"
    facts = (await record.profile_version(ctx, version.id)).facts
    assert [f.quote for f in facts if f.subject == "lung cancer"] == [DIAGNOSIS]


async def test_no_asks_again_and_a_reworded_diagnosis_gets_a_new_proposal(clean_db):
    ctx, fake, patient, _ = await _submitted(clean_db, ("small cell lung cancer", 0.8),
                                             ("non-small cell lung cancer", 0.9))
    first = await record.check_diagnosis(ctx, patient)

    rejected = await record.answer_diagnosis_check(ctx, patient, first.id, "no")

    assert rejected.status == "rejected" and rejected.ask_again and rejected.condition_term is None
    assert await record.diagnosis(ctx, patient) is None
    second = await record.check_diagnosis(ctx, patient, "NSCLC, not the small cell type")
    assert "NSCLC, not the small cell type" in fake.calls[-1].user
    assert second.id != first.id and second.suggested_term == "non-small cell lung cancer"
    await record.answer_diagnosis_check(ctx, patient, second.id, "yes")
    assert (await record.diagnosis(ctx, patient)).condition_term == "non-small cell lung cancer"


async def test_not_sure_says_check_with_the_gp_and_holds_no_condition(clean_db):
    ctx, _, patient, _ = await _submitted(clean_db, ("non-small cell lung cancer", 0.9))
    check = await record.check_diagnosis(ctx, patient)

    unsure = await record.answer_diagnosis_check(ctx, patient, check.id, "not_sure")

    assert unsure.status == "not_sure" and unsure.needs_gp and unsure.condition_term is None
    held = await record.diagnosis(ctx, patient)
    assert held.needs_gp and held.condition_term is None


async def test_a_low_confidence_proposal_is_not_offered_and_goes_straight_to_the_gp_message(clean_db):
    ctx, _, patient, _ = await _submitted(clean_db, ("lung neoplasm", 0.3))

    check = await record.check_diagnosis(ctx, patient)

    assert check.status == "unclear" and check.needs_gp and check.suggested_term is None
    assert (await record.diagnosis(ctx, patient)).needs_gp
    with pytest.raises(record.InvalidAnswers):
        await record.answer_diagnosis_check(ctx, patient, check.id, "yes")


async def test_an_answer_is_given_once_and_only_to_the_patients_own_check(clean_db):
    ctx, _, patient, _ = await _submitted(clean_db, ("non-small cell lung cancer", 0.9))
    check = await record.check_diagnosis(ctx, patient)
    other = await record.create_patient(ctx, "Demo patient E")

    with pytest.raises(record.NotFound):
        await record.answer_diagnosis_check(ctx, other, check.id, "yes")
    await record.answer_diagnosis_check(ctx, patient, check.id, "yes")
    with pytest.raises(record.InvalidAnswers):
        await record.answer_diagnosis_check(ctx, patient, check.id, "no")


async def test_checking_before_any_diagnosis_answer_raises_not_found(clean_db):
    from tests.conftest import make_ctx
    fake = fake_model()
    ctx = make_ctx(clean_db, fake)
    patient = await record.create_patient(ctx, "Demo patient F")

    with pytest.raises(record.NotFound):
        await record.check_diagnosis(ctx, patient)
    assert fake.calls == []
