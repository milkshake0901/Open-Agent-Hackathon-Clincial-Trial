"""Seam 1 (spec #5): the record facade. Correcting an answer is a full resubmission (ADR 0003): a new Document
and Profile version, with unchanged answers dropped as duplicates. Observed through submit_questionnaire and diff."""
from __future__ import annotations

from app import record

ANSWERS = {
    "birth_month": "1958-03",
    "sex": "female",
    "has_allergies": "no",
    "daily_activity": "light_activity",
    "pregnancy": "no",
}


async def _submit(ctx, patient, answers, respondent="patient"):
    outcome = await record.submit_questionnaire(ctx, patient, answers, respondent=respondent)
    assert isinstance(outcome, record.Committed), outcome
    return outcome.version


async def test_resubmitting_identical_answers_adds_no_document_and_no_facts(ctx):
    patient = await record.create_patient(ctx, "Demo patient A")
    first = await _submit(ctx, patient, ANSWERS)
    again = await _submit(ctx, patient, dict(ANSWERS))

    assert again.document_hash == first.document_hash and again.id == first.id
    current = await record.current_version(ctx, patient)
    assert current.number == 1 and current.fact_ids == first.fact_ids


async def test_changing_one_answer_makes_a_new_version_whose_diff_shows_only_that_subject(ctx):
    patient = await record.create_patient(ctx, "Demo patient B")
    v1 = await _submit(ctx, patient, ANSWERS)
    v2 = await _submit(ctx, patient, {**ANSWERS, "daily_activity": "self_care"})

    assert v2.number == 2 and v2.document_hash != v1.document_hash
    d = await record.diff(ctx, v1.id, v2.id)
    assert [(f.subject, f.value, f.question) for f in d.facts_added] == [("daily activity", "self_care", "Q13")]
    assert [(s, before.value, after.value) for s, before, after in d.subjects_changed] == [
        ("daily activity", "light_activity", "self_care")]


async def test_changing_an_answer_back_is_a_correction_too_and_earlier_versions_stay_intact(ctx):
    patient = await record.create_patient(ctx, "Demo patient C")
    v1 = await _submit(ctx, patient, ANSWERS)
    v2 = await _submit(ctx, patient, {**ANSWERS, "daily_activity": "self_care"})
    v3 = await _submit(ctx, patient, ANSWERS)

    assert v3.number == 3 and len({v1.document_hash, v2.document_hash, v3.document_hash}) == 3
    d = await record.diff(ctx, v2.id, v3.id)
    assert [(s, before.value, after.value) for s, before, after in d.subjects_changed] == [
        ("daily activity", "self_care", "light_activity")]
    assert (await record.current_version(ctx, patient)).current()["daily activity"].value == "light_activity"
    assert (await record.profile_version(ctx, v2.id)).current()["daily activity"].value == "self_care"


async def test_a_correction_on_a_later_day_still_adds_only_the_changed_answer(ctx):
    from dataclasses import replace
    from datetime import datetime, UTC

    patient = await record.create_patient(ctx, "Demo patient D")
    v1 = await _submit(ctx, patient, ANSWERS)
    next_week = replace(ctx, now=lambda: datetime(2026, 10, 31, 9, 0, tzinfo=UTC))
    v2 = await _submit(next_week, patient, {**ANSWERS, "has_allergies": "yes"})

    d = await record.diff(ctx, v1.id, v2.id)
    assert [(f.subject, f.value, str(f.observed_on)) for f in d.facts_added] == [("any allergy", "yes", "2026-10-31")]
    assert [s for s, _, _ in d.subjects_changed] == ["any allergy"]


async def test_changing_only_a_free_text_answer_makes_a_version_with_no_new_facts(ctx):
    patient = await record.create_patient(ctx, "Demo patient E")
    v1 = await _submit(ctx, patient, ANSWERS)
    v2 = await _submit(ctx, patient, {**ANSWERS, "medicines": "Paracetamol when needed"})

    assert v2.number == 2 and v2.document_hash != v1.document_hash
    d = await record.diff(ctx, v1.id, v2.id)
    assert d.facts_added == () and d.subjects_changed == ()
