"""Seam 1 (spec #5): the record facade, for free-text answers (#8). Free text goes through the Intake agent
(a scripted fake model here); observe the result through profile_version and the prompts the fake captured."""
from __future__ import annotations

from datetime import date

from app import record
from app.llm.nightshift import FakeLLM

ANSWERS = {
    "sex": "female",
    "postcode": "2031",
    "diagnosis": "Breast cancer, HER2 positive",
    "diagnosis_when": "around March 2024",
    "treatments": "Surgery in 2024. Chemo ended around March 2025.",
    "medicines": "Tamoxifen 20 mg daily",
    "has_allergies": "yes",
    "allergies": "Penicillin (rash)",
}

# Pages, one per rendered section: 1 about, 2 diagnosis, 3 treatment, 4 medicines, 5 allergies, 6 other health,
# 7 daily activity, 8 pregnancy.
MODEL_FACTS = [
    {"resource": "Condition", "subject": "breast cancer", "value": "HER2 positive", "observed_on": "2024-03",
     "page": 2, "quote": "Breast cancer, HER2 positive", "question": "Q6"},
    {"resource": "Procedure", "subject": "chemotherapy", "value": "ended", "observed_on": "2025-03",
     "page": 3, "quote": "Chemo ended around March 2025", "question": "Q8"},
    {"resource": "MedicationStatement", "subject": "tamoxifen", "value": "20 mg daily", "observed_on": "2026-10-24",
     "page": 4, "quote": "Tamoxifen 20 mg daily", "question": "Q9"},
    {"resource": "Observation", "subject": "penicillin", "value": "rash", "observed_on": "2026-10-24",
     "page": 5, "quote": "Penicillin (rash)", "question": "Q11"},
]


def scripted(*attempts):
    """A fake model that answers each Intake call with the next scripted fact list (the last one repeats)."""
    replies = list(attempts)
    return FakeLLM(lambda lane, system, user: {"facts": replies.pop(0) if len(replies) > 1 else replies[0]})


async def _submit(ctx, answers=ANSWERS, respondent="patient"):
    patient = await record.create_patient(ctx, "Demo patient J")
    return await record.submit_questionnaire(ctx, patient, answers, respondent=respondent)


async def test_free_text_answers_become_patient_reported_facts_through_the_intake_agent(clean_db):
    from tests.conftest import make_ctx
    fake = scripted(MODEL_FACTS)
    ctx = make_ctx(clean_db, fake)

    outcome = await _submit(ctx)

    assert isinstance(outcome, record.Committed)
    assert len(fake.calls) == 1 and fake.calls[0].lane == "fast"
    version = await record.profile_version(ctx, outcome.version.id)
    got = {(f.resource, f.subject, f.value, f.question, f.quote) for f in version.facts}
    assert ("Condition", "breast cancer", "HER2 positive", "Q6", "Breast cancer, HER2 positive") in got
    assert ("MedicationStatement", "tamoxifen", "20 mg daily", "Q9", "Tamoxifen 20 mg daily") in got
    # structured answers are still mapped in code, next to the model's Facts
    assert ("Patient", "sex assigned at birth", "female", "Q3", "Female") in got
    assert ("AllergyIntolerance", "any allergy", "yes", "Q10", "Yes") in got


async def test_an_allergy_answer_is_stored_as_an_allergy_intolerance_fact(clean_db):
    from tests.conftest import make_ctx
    ctx = make_ctx(clean_db, scripted(MODEL_FACTS))   # the model calls the allergy an Observation

    outcome = await _submit(ctx)

    version = await record.profile_version(ctx, outcome.version.id)
    penicillin = next(f for f in version.facts if f.subject == "penicillin")
    assert penicillin.resource == "AllergyIntolerance"
    assert (penicillin.question, penicillin.quote, penicillin.page) == ("Q11", "Penicillin (rash)", 5)


async def test_an_approximate_date_is_kept_as_a_best_estimate_with_the_respondents_words(clean_db):
    from tests.conftest import make_ctx
    fake = scripted(MODEL_FACTS)
    ctx = make_ctx(clean_db, fake)

    outcome = await _submit(ctx)

    assert isinstance(outcome, record.Committed)
    assert len(fake.calls) == 1   # accepted on the first attempt: no MISSING_DATE retry
    facts = {f.subject: f for f in (await record.profile_version(ctx, outcome.version.id)).facts}
    assert facts["chemotherapy"].observed_on == date(2025, 3, 15)
    assert facts["chemotherapy"].quote == "Chemo ended around March 2025"
    assert facts["breast cancer"].observed_on == date(2024, 3, 15)
    assert facts["tamoxifen"].observed_on == date(2026, 10, 24)


async def test_the_intake_agent_sees_only_the_free_text_answers_never_the_postcode(clean_db):
    from tests.conftest import make_ctx
    fake = scripted(MODEL_FACTS)
    ctx = make_ctx(clean_db, fake)

    await _submit(ctx)

    prompt = fake.calls[0].system + fake.calls[0].user
    assert "Chemo ended around March 2025" in prompt and "Q8." in prompt and "Page 3" in prompt
    assert "2031" not in prompt
    assert "Female" not in prompt and "Q3." not in prompt   # structured answers stay with code


async def test_other_critic_checks_still_apply_to_questionnaire_answers(clean_db):
    from tests.conftest import make_ctx
    wrong_quote = {**MODEL_FACTS[1], "quote": "Chemo ended in January 2025"}
    no_date = {**MODEL_FACTS[2], "observed_on": None}
    fake = scripted([MODEL_FACTS[0], wrong_quote, no_date, MODEL_FACTS[3]], MODEL_FACTS)
    ctx = make_ctx(clean_db, fake)

    outcome = await _submit(ctx)

    assert isinstance(outcome, record.Committed)
    assert len(fake.calls) == 2
    retry = fake.calls[1].user
    assert "quote not found on page 3" in retry and "no observed-on date" in retry
    facts = {f.subject: f for f in (await record.profile_version(ctx, outcome.version.id)).facts}
    assert facts["chemotherapy"].quote == "Chemo ended around March 2025"


async def test_a_questionnaire_with_no_free_text_makes_no_model_call(ctx, fake_llm):
    outcome = await _submit(ctx, {"sex": "female", "has_allergies": "no", "allergies": "  "})

    assert isinstance(outcome, record.Committed)
    assert fake_llm.calls == []


async def test_when_the_model_is_unavailable_the_submission_is_rejected_not_crashed(ctx, fake_llm):
    outcome = await _submit(ctx)   # fake_llm has no script: every call fails

    assert isinstance(outcome, record.Rejected)
    assert "unavailable" in outcome.reason
