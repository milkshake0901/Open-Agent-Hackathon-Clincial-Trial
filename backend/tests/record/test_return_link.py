"""Seam: the record facade. A private return link reopens one patient's record; search preferences
(postcode, travel limit, optional contact) are stored on the patient, never as Facts (ADR 0003, #10)."""
from __future__ import annotations

import pytest

from app import record


async def test_a_return_token_reopens_only_the_patient_it_was_issued_for(ctx):
    a = await record.create_patient(ctx, "Demo patient A")
    b = await record.create_patient(ctx, "Demo patient B")

    token_a = await record.issue_return_token(ctx, a)
    token_b = await record.issue_return_token(ctx, b)

    assert token_a != token_b and len(token_a) >= 32
    assert await record.patient_for_return_token(ctx, token_a) == a
    assert await record.patient_for_return_token(ctx, token_b) == b


async def test_an_invalid_token_opens_no_patient(ctx):
    a = await record.create_patient(ctx, "Demo patient A")
    token = await record.issue_return_token(ctx, a)

    for wrong in ("nope", token[:-1], token.upper(), ""):
        with pytest.raises(record.NotFound) as e:
            await record.patient_for_return_token(ctx, wrong)
        assert a not in str(e.value) and "Demo" not in str(e.value)


async def test_the_token_is_issued_once_per_patient(ctx):
    a = await record.create_patient(ctx, "Demo patient A")
    first = await record.issue_return_token(ctx, a)

    assert await record.issue_return_token(ctx, a) is None
    assert await record.patient_for_return_token(ctx, first) == a


PRIVATE = {"postcode": "2031", "max_travel_km": "50", "contact": "sam.carer@example.com"}


async def test_postcode_travel_limit_and_contact_are_stored_as_search_preferences(ctx):
    patient = await record.create_patient(ctx, "Demo patient A")

    await record.submit_questionnaire(ctx, patient, {"sex": "female", **PRIVATE}, respondent="other")

    assert await record.search_preferences(ctx, patient) == record.SearchPreferences(
        postcode="2031", max_travel_km=50, contact="sam.carer@example.com")


async def test_search_preferences_are_never_facts_document_text_or_model_input(ctx, fake_llm):
    patient = await record.create_patient(ctx, "Demo patient A")

    outcome = await record.submit_questionnaire(
        ctx, patient, {"sex": "female", "diagnosis": "breast cancer", **PRIVATE}, respondent="patient")

    version = await record.profile_version(ctx, outcome.version.id)
    doc = await record.document(ctx, version.document_hash)
    stored = " ".join([p.text for p in doc.pages] + [f"{f.subject} {f.value} {f.quote}" for f in version.facts])
    prompts = " ".join(f"{c}" for c in fake_llm.calls)
    for secret in ("2031", "sam.carer", "example.com"):
        assert secret not in stored and secret not in prompts


async def test_a_patient_without_answers_has_empty_search_preferences(ctx):
    patient = await record.create_patient(ctx, "Demo patient A")
    await record.submit_questionnaire(ctx, patient, {"sex": "female", "max_travel_km": "anywhere"}, respondent="patient")

    assert await record.search_preferences(ctx, patient) == record.SearchPreferences(None, None, None)


async def test_a_resubmission_keeps_preferences_it_leaves_blank(ctx):
    patient = await record.create_patient(ctx, "Demo patient A")
    await record.submit_questionnaire(ctx, patient, {"sex": "female", **PRIVATE}, respondent="patient")

    await record.submit_questionnaire(ctx, patient, {"sex": "female", "max_travel_km": "100"}, respondent="patient")

    assert await record.search_preferences(ctx, patient) == record.SearchPreferences(
        postcode="2031", max_travel_km=100, contact="sam.carer@example.com")


@pytest.mark.parametrize("answers", [{"postcode": "20311"}, {"postcode": "Sydney"}, {"contact": "not a contact"}])
async def test_malformed_preferences_are_rejected_before_anything_is_stored(ctx, answers):
    patient = await record.create_patient(ctx, "Demo patient A")

    with pytest.raises(record.InvalidAnswers):
        await record.submit_questionnaire(ctx, patient, {"sex": "female", **answers}, respondent="patient")
    assert await record.search_preferences(ctx, patient) == record.SearchPreferences(None, None, None)
    assert await record.current_version(ctx, patient) is None
