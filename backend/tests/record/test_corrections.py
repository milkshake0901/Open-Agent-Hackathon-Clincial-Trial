"""Seam 1 (spec #5): the record facade. Correcting an answer is a full resubmission (ADR 0003): a new Document
and Profile version, with unchanged answers dropped as duplicates. Observed through submit_questionnaire and diff."""
from __future__ import annotations

from app import record
from app.llm.nightshift import FakeLLM

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


def _quiet_model_ctx(clean_db):
    """Free-text answers go to the Intake agent (#8); this fake model finds no Facts in them."""
    from tests.conftest import make_ctx
    return make_ctx(clean_db, FakeLLM(lambda lane, system, user: {"facts": []}))


async def test_changing_only_a_free_text_answer_makes_a_version_with_no_new_facts(clean_db):
    ctx = _quiet_model_ctx(clean_db)
    patient = await record.create_patient(ctx, "Demo patient E")
    v1 = await _submit(ctx, patient, ANSWERS)
    v2 = await _submit(ctx, patient, {**ANSWERS, "medicines": "Paracetamol when needed"})

    assert v2.number == 2 and v2.document_hash != v1.document_hash
    d = await record.diff(ctx, v1.id, v2.id)
    assert d.facts_added == () and d.subjects_changed == ()


async def test_the_latest_submission_can_be_read_back_to_prefill_an_edit(clean_db):
    ctx = _quiet_model_ctx(clean_db)
    patient = await record.create_patient(ctx, "Demo patient F")
    assert await record.latest_answers(ctx, patient) is None
    await _submit(ctx, patient, ANSWERS)
    edited = {**ANSWERS, "sex": "prefer_not_to_say", "pregnancy": None,
              "treatments": "Chemotherapy  in 2024,\nthen surgery", "postcode": "2031"}
    await _submit(ctx, patient, edited, respondent="other")

    latest = await record.latest_answers(ctx, patient)

    assert latest.respondent == "other"
    assert latest.answers == {"birth_month": "1958-03", "sex": "prefer_not_to_say", "has_allergies": "no",
                              "daily_activity": "light_activity", "treatments": "Chemotherapy in 2024, then surgery"}


async def test_a_free_text_fact_the_model_finds_again_in_a_correction_is_dropped_as_a_duplicate(clean_db):
    from tests.conftest import make_ctx
    tamoxifen = {"resource": "MedicationStatement", "subject": "tamoxifen", "value": "20 mg daily",
                 "observed_on": "2026-10-24", "page": 4, "quote": "Tamoxifen 20 mg daily", "question": "Q9"}
    ctx = make_ctx(clean_db, FakeLLM(lambda lane, system, user: {"facts": [tamoxifen]}))
    patient = await record.create_patient(ctx, "Demo patient G")
    answers = {**ANSWERS, "medicines": "Tamoxifen 20 mg daily"}
    v1 = await _submit(ctx, patient, answers)
    v2 = await _submit(ctx, patient, {**answers, "sex": "intersex"})

    d = await record.diff(ctx, v1.id, v2.id)
    assert [f.subject for f in d.facts_added] == ["sex assigned at birth"]


async def test_an_edit_never_reads_back_the_postcode_or_contact_and_leaving_them_blank_keeps_them(ctx):
    patient = await record.create_patient(ctx, "Demo patient H")
    await _submit(ctx, patient, {**ANSWERS, "postcode": "2031", "max_travel_km": "50", "contact": "a@example.org"})

    latest = await record.latest_answers(ctx, patient)
    assert not {"postcode", "max_travel_km", "contact"} & set(latest.answers)
    assert "2031" not in repr(latest) and "example.org" not in repr(latest)

    await _submit(ctx, patient, {**latest.answers, "daily_activity": "self_care"})
    prefs = await record.search_preferences(ctx, patient)
    assert (prefs.postcode, prefs.contact) == ("2031", "a@example.org")


async def test_a_free_text_answer_reworded_more_exactly_is_kept_though_its_value_is_unchanged(clean_db):
    from tests.conftest import make_ctx
    vague, exact = "Chemo finished sometime this year", "Chemo finished on 30 September 2026"
    drafts = {vague: "2026", exact: "2026-09-30"}

    def intake(lane, system, user):
        words = next(w for w in drafts if w in user)
        return {"facts": [{"resource": "Procedure", "subject": "chemotherapy", "value": "ended",
                           "observed_on": drafts[words], "page": 3, "quote": words, "question": "Q8"}]}
    ctx = make_ctx(clean_db, FakeLLM(intake))
    patient = await record.create_patient(ctx, "Demo patient K")
    v1 = await _submit(ctx, patient, {**ANSWERS, "treatments": vague})
    v2 = await _submit(ctx, patient, {**ANSWERS, "treatments": exact})

    d = await record.diff(ctx, v1.id, v2.id)
    assert [(f.subject, f.quote) for f in d.facts_added] == [("chemotherapy", exact)]
