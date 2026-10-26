"""Seam 1 (spec #5): the record facade, for Conflicts (#13). A Patient-reported Fact from the Intake questionnaire
and a clinical Document that contradicts it: record.ingest parks the run AwaitingPatient with a Conflict citing
both sides, and record.confirm commits the Respondent's choice as the next Profile version. The Intake model is a
scripted fake and Nemotron Parse replays hand-made recordings; every name and number in them is invented."""
from __future__ import annotations

from dataclasses import replace

import pytest

from app import record
from app.config import Settings
from tests.conftest import ADMIN_DSN, make_ctx
from tests.fixtures.letters import letter_pdf, recorded, recording
from tests.record.test_adding_documents import by_document
from tests.review import confirm_as_read, ingest_as_read

REFERRAL_READ = recording(
    "Oncology referral letter\nDear colleague,",
    "Diagnosis: HER2 positive breast cancer, confirmed 2024-03-12.\nECOG 2 on 2026-10-20.",
)
REFERRAL = letter_pdf(REFERRAL_READ, "conflicting referral")
REFERRAL_FACTS = [
    {"resource": "Condition", "subject": "breast cancer", "value": "HER2 positive", "observed_on": "2024-03-12",
     "page": 2, "quote": "HER2 positive breast cancer"},
    {"resource": "Observation", "subject": "ECOG performance status", "value": "2", "unit": "score",
     "observed_on": "2026-10-20", "page": 2, "quote": "ECOG 2 on 2026-10-20"},
]
OLD_LETTER_READ = recording("Clinic letter\nECOG 2 on 2025-01-10.")
OLD_LETTER = letter_pdf(OLD_LETTER_READ, "old letter")
OLD_LETTER_FACTS = [
    {"resource": "Observation", "subject": "ECOG performance status", "value": "2", "unit": "score",
     "observed_on": "2025-01-10", "page": 1, "quote": "ECOG 2 on 2025-01-10"},
]
AGREEING_READ = recording("Clinic review\nECOG 0 on 2026-10-21.")
AGREEING = letter_pdf(AGREEING_READ, "agreeing review")
AGREEING_FACTS = [
    {"resource": "Observation", "subject": "ecog", "value": "0", "unit": "score", "observed_on": "2026-10-21",
     "page": 1, "quote": "ECOG 0 on 2026-10-21"},
]


def parse():
    """Nemotron Parse replaying what it reads from each generated PDF in this file."""
    return recorded((REFERRAL, REFERRAL_READ), (OLD_LETTER, OLD_LETTER_READ), (AGREEING, AGREEING_READ),
                    (TWO_CONFLICTS, TWO_CONFLICTS_READ))


@pytest.fixture
def conflict_ctx(clean_db, tmp_path):
    fake = by_document(referral=REFERRAL_FACTS, **{"Clinic letter": OLD_LETTER_FACTS, "Clinic review": AGREEING_FACTS})
    ctx = make_ctx(clean_db, fake, parser=parse())
    return replace(ctx, settings=Settings(_env_file=None, pg_dsn=ADMIN_DSN, raw_documents_dir=str(tmp_path)))


async def _fully_active_patient(ctx):
    patient = await record.create_patient(ctx, "Demo patient C")
    v1 = await record.submit_questionnaire(ctx, patient, {"sex": "female", "daily_activity": "fully_active"},
                                           respondent="patient")
    assert isinstance(v1, record.Committed)
    return patient, v1.version


async def _add(ctx, patient, name, content):
    registered = await record.register_document(ctx, patient, name, content)
    return registered.document.hash, await ingest_as_read(ctx, registered.document.hash)


async def test_a_letter_contradicting_the_questionnaire_waits_on_the_patient_with_both_sides(conflict_ctx):
    ctx = conflict_ctx
    patient, v1 = await _fully_active_patient(ctx)

    letter, outcome = await _add(ctx, patient, "referral.pdf", REFERRAL)

    assert isinstance(outcome, record.AwaitingPatient)
    [conflict] = outcome.conflicts
    assert (conflict.document_hash, conflict.draft.page, conflict.draft.value, conflict.draft.quote) == (
        letter, 2, "2", "ECOG 2 on 2026-10-20")
    assert (conflict.accepted.document_hash, conflict.accepted.question, conflict.accepted.value) == (
        v1.document_hash, "Q13", "fully_active")
    assert conflict.accepted.page >= 1 and conflict.message
    assert (await record.current_version(ctx, patient)).number == 1


async def test_a_letter_that_agrees_or_describes_another_time_commits_without_asking(conflict_ctx):
    ctx = conflict_ctx
    patient, _ = await _fully_active_patient(ctx)

    _, agreeing = await _add(ctx, patient, "review.pdf", AGREEING)
    _, old = await _add(ctx, patient, "old.pdf", OLD_LETTER)

    assert isinstance(agreeing, record.Committed) and agreeing.version.number == 2
    assert isinstance(old, record.Committed) and old.version.number == 3


async def test_ingesting_a_parked_document_again_returns_the_same_conflict_without_a_model_call(conflict_ctx):
    ctx = conflict_ctx
    patient, _ = await _fully_active_patient(ctx)
    letter, parked = await _add(ctx, patient, "referral.pdf", REFERRAL)
    calls = len(ctx.llm.calls)

    again = await ingest_as_read(ctx, letter)

    assert again == parked
    assert len(ctx.llm.calls) == calls


async def test_accepting_the_letter_commits_its_value_as_the_next_version(conflict_ctx):
    ctx = conflict_ctx
    patient, v1 = await _fully_active_patient(ctx)
    letter, parked = await _add(ctx, patient, "referral.pdf", REFERRAL)
    [conflict] = parked.conflicts

    outcome = await confirm_as_read(ctx, parked.run_id, [record.Resolution(conflict.id, "accept_draft")])

    assert isinstance(outcome, record.Committed) and outcome.run_id == parked.run_id
    v2 = await record.profile_version(ctx, outcome.version.id)
    assert (v2.number, v2.document_hash) == (2, letter)
    subjects = {f.subject: f for f in v2.facts}
    assert subjects["ecog performance status"].value == "2"
    assert "daily activity" not in subjects          # the answer the Respondent overruled is no longer accepted
    assert {"sex assigned at birth", "breast cancer"} <= set(subjects)
    assert conflict.accepted.id in (await record.profile_version(ctx, v1.id)).fact_ids   # v1 keeps it


async def test_keeping_the_answer_drops_the_letters_value_but_commits_the_rest_of_the_letter(conflict_ctx):
    ctx = conflict_ctx
    patient, _ = await _fully_active_patient(ctx)
    _, parked = await _add(ctx, patient, "referral.pdf", REFERRAL)

    outcome = await confirm_as_read(ctx, parked.run_id, [record.Resolution(parked.conflicts[0].id, "keep_accepted")])

    v2 = await record.profile_version(ctx, outcome.version.id)
    subjects = {f.subject: f.value for f in v2.facts}
    assert v2.number == 2 and subjects["daily activity"] == "fully_active" and "breast cancer" in subjects
    assert "ecog performance status" not in subjects


async def test_discarding_both_leaves_neither_value_in_the_next_version(conflict_ctx):
    ctx = conflict_ctx
    patient, _ = await _fully_active_patient(ctx)
    _, parked = await _add(ctx, patient, "referral.pdf", REFERRAL)

    outcome = await confirm_as_read(ctx, parked.run_id, [record.Resolution(parked.conflicts[0].id, "discard_both")])

    subjects = {f.subject for f in (await record.profile_version(ctx, outcome.version.id)).facts}
    assert {"daily activity", "ecog performance status"}.isdisjoint(subjects) and "breast cancer" in subjects


TWO_CONFLICTS_READ = recording("Discharge summary\nSex: male. ECOG 2 on 2026-10-20.")
TWO_CONFLICTS = letter_pdf(TWO_CONFLICTS_READ, "discharge")
TWO_CONFLICTS_FACTS = [
    {"resource": "Patient", "subject": "sex assigned at birth", "value": "male", "observed_on": "2026-10-20",
     "page": 1, "quote": "Sex: male"},
    {"resource": "Observation", "subject": "ecog", "value": "2", "unit": "score", "observed_on": "2026-10-20",
     "page": 1, "quote": "ECOG 2 on 2026-10-20"},
]


async def test_a_partial_answer_keeps_waiting_on_the_rest_and_a_finished_run_cannot_be_confirmed_again(clean_db, tmp_path):
    ctx = make_ctx(clean_db, by_document(Discharge=TWO_CONFLICTS_FACTS), parser=parse())
    ctx = replace(ctx, settings=Settings(_env_file=None, pg_dsn=ADMIN_DSN, raw_documents_dir=str(tmp_path)))
    patient, _ = await _fully_active_patient(ctx)
    _, parked = await _add(ctx, patient, "discharge.pdf", TWO_CONFLICTS)
    sex, ecog = sorted(parked.conflicts, key=lambda c: c.draft.subject != "sex assigned at birth")

    first = await confirm_as_read(ctx, parked.run_id, [record.Resolution(sex.id, "keep_accepted")])
    with pytest.raises(record.InvalidResolution):
        await confirm_as_read(ctx, parked.run_id, [record.Resolution(sex.id, "accept_draft")])
    done = await confirm_as_read(ctx, parked.run_id, [record.Resolution(ecog.id, "accept_draft")])

    assert isinstance(first, record.AwaitingPatient) and [c.id for c in first.conflicts] == [ecog.id]
    assert isinstance(done, record.Committed) and done.version.number == 2
    values = {f.subject: f.value for f in (await record.profile_version(ctx, done.version.id)).facts}
    assert (values["sex assigned at birth"], values["ecog"]) == ("female", "2") and "daily activity" not in values
    with pytest.raises(record.NotAwaitingPatient):
        await confirm_as_read(ctx, parked.run_id, [])
