"""Seam 1 (spec #5): the record facade. Submit with submit_questionnaire, observe through profile_version."""
from __future__ import annotations

from app import record


def _questions():
    return [q for s in record.questionnaire_definition().sections for q in s.questions]


def test_definition_has_the_structured_questions_and_every_one_can_be_skipped():
    ids = {q.id for q in _questions()}
    assert {"respondent", "birth_month", "sex", "daily_activity", "pregnancy"} <= ids
    assert all(not q.required for q in _questions())


def test_definition_words_each_question_for_the_patient_and_for_someone_else():
    sex = next(q for q in _questions() if q.id == "sex")
    assert "your" in sex.label.lower() and "their" in sex.label_other.lower()
    assert [o.label for o in sex.options] == ["Female", "Male", "Intersex", "Prefer not to say"]


def test_definition_never_asks_for_name_full_date_of_birth_or_street_address():
    text = " ".join(f"{q.id} {q.label} {q.label_other} {q.help or ''}" for q in _questions()).lower()
    for banned in ("name", "date of birth", "street", "address", "medicare"):
        assert banned not in text
    birth = next(q for q in _questions() if q.id == "birth_month")
    assert birth.kind == "month_year"


ANSWERS = {
    "birth_month": "1958-03",
    "sex": "female",
    "has_allergies": "no",
    "daily_activity": "light_activity",
    "pregnancy": "no",
}


async def test_structured_answers_commit_profile_v1_without_calling_the_model(ctx, fake_llm):
    patient = await record.create_patient(ctx, "Demo patient A")

    outcome = await record.submit_questionnaire(ctx, patient, ANSWERS, respondent="patient")

    assert isinstance(outcome, record.Committed)
    assert outcome.version.number == 1
    assert fake_llm.calls == []
    version = await record.profile_version(ctx, outcome.version.id)
    got = {(f.resource, f.subject, f.value, f.question) for f in version.facts}
    assert got == {
        ("Patient", "birth month", "1958-03", "Q2"),
        ("Patient", "sex assigned at birth", "female", "Q3"),
        ("AllergyIntolerance", "any allergy", "no", "Q10"),
        ("Observation", "daily activity", "light_activity", "Q13"),
        ("Observation", "pregnant, breastfeeding or planning a pregnancy", "no", "Q14"),
    }
    assert all(str(f.observed_on) == "2026-10-24" for f in version.facts)


async def test_each_fact_quotes_the_answer_text_on_its_section_page(ctx):
    patient = await record.create_patient(ctx, "Demo patient A")
    outcome = await record.submit_questionnaire(ctx, patient, ANSWERS, respondent="patient")

    version = await record.profile_version(ctx, outcome.version.id)
    doc = await record.document(ctx, version.document_hash)
    quotes = {f.subject: f.quote for f in version.facts}
    assert quotes["birth month"] == "March 1958"
    assert quotes["daily activity"] == "Can't do heavy physical work, but can do light work such as housework"
    for f in version.facts:
        page = doc.pages[f.page - 1].text
        assert f"{f.question}." in page and f"Answer: {f.quote}" in page


async def test_the_respondent_is_stored_with_the_document_not_as_a_fact(ctx):
    patient = await record.create_patient(ctx, "Demo patient B")
    outcome = await record.submit_questionnaire(ctx, patient, ANSWERS, respondent="other")

    doc = await record.document(ctx, outcome.version.document_hash)
    assert doc.respondent == "other"
    assert "their sex assigned at birth" in doc.pages[0].text
    version = await record.profile_version(ctx, outcome.version.id)
    assert not any("respond" in f.subject or f.value in ("patient", "other") for f in version.facts)


async def test_skipped_and_prefer_not_to_say_answers_make_no_facts(ctx):
    patient = await record.create_patient(ctx, "Demo patient C")
    outcome = await record.submit_questionnaire(
        ctx, patient, {"sex": "prefer_not_to_say", "birth_month": "", "daily_activity": "fully_active"},
        respondent="patient")

    version = await record.profile_version(ctx, outcome.version.id)
    assert [f.subject for f in version.facts] == ["daily activity"]


async def test_postcode_and_travel_limit_are_not_facts_and_not_in_the_document(ctx):
    patient = await record.create_patient(ctx, "Demo patient D")
    outcome = await record.submit_questionnaire(
        ctx, patient, {**ANSWERS, "postcode": "2031", "max_travel_km": "50"}, respondent="patient")

    version = await record.profile_version(ctx, outcome.version.id)
    doc = await record.document(ctx, version.document_hash)
    assert not any("2031" in p.text for p in doc.pages)
    assert not any("2031" in (f.value + f.quote) for f in version.facts)


async def test_an_answer_that_does_not_fit_its_question_is_rejected_before_anything_is_stored(ctx):
    patient = await record.create_patient(ctx, "Demo patient E")
    for bad in ({"sex": "unknown"}, {"birth_month": "1958-13"}, {"full_name": "x"}):
        try:
            await record.submit_questionnaire(ctx, patient, bad, respondent="patient")
        except record.InvalidAnswers:
            continue
        raise AssertionError(f"{bad} was accepted")
    assert await record.current_version(ctx, patient) is None


async def test_after_a_restart_the_next_submission_becomes_profile_v2(clean_db, fake_llm):
    from tests.conftest import make_ctx

    first = make_ctx(clean_db, fake_llm)
    patient = await record.create_patient(first, "Demo patient F")
    v1 = await record.submit_questionnaire(first, patient, ANSWERS, respondent="patient")

    restarted = make_ctx(clean_db, fake_llm)
    await restarted.wm.replay()
    v2 = await record.submit_questionnaire(restarted, patient, {**ANSWERS, "daily_activity": "self_care"},
                                           respondent="patient")

    assert isinstance(v2, record.Committed) and v2.version.number == 2
    version = await record.profile_version(restarted, v2.version.id)
    assert v1.version.fact_ids < version.fact_ids
    assert version.current()["daily activity"].value == "self_care"


async def test_submitting_identical_answers_again_returns_the_same_version(ctx):
    patient = await record.create_patient(ctx, "Demo patient G")
    first = await record.submit_questionnaire(ctx, patient, ANSWERS, respondent="patient")
    again = await record.submit_questionnaire(ctx, patient, ANSWERS, respondent="patient")

    assert again.version.id == first.version.id and again.run_id == first.run_id
    assert (await record.current_version(ctx, patient)).number == 1


async def test_two_patients_with_the_same_answers_get_separate_documents(ctx):
    a = await record.create_patient(ctx, "Demo patient H")
    b = await record.create_patient(ctx, "Demo patient I")
    va = await record.submit_questionnaire(ctx, a, ANSWERS, respondent="patient")
    vb = await record.submit_questionnaire(ctx, b, ANSWERS, respondent="patient")

    assert va.version.document_hash != vb.version.document_hash
    assert vb.version.number == 1 and vb.version.patient_id == b
