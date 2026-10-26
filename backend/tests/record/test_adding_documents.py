"""Seam 1 (spec #5): the record facade, for adding clinical Documents (#11). A Document goes through
register_document (hash, pages, de-identification) and ingest (Intake ⇄ Critic, a scripted fake model here);
observe the result through record.document, profile_version and the prompts the fake model captured.
Nemotron Parse is replayed from hand-made recordings (tests/fixtures/letters.py), and every name, number and address
in them is invented."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date

import pytest

from app import record
from app.config import Settings
from app.llm.nightshift import FakeLLM
from tests.conftest import ADMIN_DSN, make_ctx
from tests.fixtures.letters import intake_reading, letter_pdf, recorded, recording
from tests.review import ingest_as_read

REFERRAL_READ = recording(
    "Oncology referral letter\n"
    "Patient: Jane Citizen\n"
    "MRN: 4455667\n"
    "Medicare: 2123 45670 1\n"
    "DOB: 03/02/1961\n"
    "Address: 12 Example Street, Sydney NSW 2000\n"
    "Phone: (02) 9123 4567\n"
    "Email: jane.citizen@example.com\n"
    "Dear Dr Alan Example,",
    "Diagnosis: HER2 positive breast cancer, confirmed 2024-03-12.\n"
    "ECOG 1 on 2026-09-30.\n"
    "Signed: Dr Alan Example",
)
REFERRAL = letter_pdf(REFERRAL_READ, "referral")
REFERRAL_FACTS = [
    {"resource": "Condition", "subject": "breast cancer", "value": "HER2 positive", "observed_on": "2024-03-12",
     "page": 2, "quote": "HER2 positive breast cancer"},
    {"resource": "Observation", "subject": "ecog", "value": "1", "unit": "score", "observed_on": "2026-09-30",
     "page": 2, "quote": "ECOG 1 on 2026-09-30"},
]
BLOODS_READ = recording("Pathology report\nHaemoglobin 118 g/L collected 2026-10-01")
BLOODS = letter_pdf(BLOODS_READ, "bloods")
BLANK_READ = recording("")
BLANK = letter_pdf(BLANK_READ, "blank")
PARSE = ((REFERRAL, REFERRAL_READ), (BLOODS, BLOODS_READ), (BLANK, BLANK_READ))
"""What Nemotron Parse reads from each generated PDF: invented text, one Text Region per line."""
BLOODS_FACTS = [
    {"resource": "Observation", "subject": "haemoglobin", "value": "118", "unit": "g/L", "observed_on": "2026-10-01",
     "page": 1, "quote": "Haemoglobin 118 g/L"},
]
IDENTIFIERS = ("Jane", "Citizen", "4455667", "2123 45670 1", "03/02/1961", "12 Example Street", "9123 4567",
               "jane.citizen@example.com", "Alan")


class SlowFakeLLM(FakeLLM):
    """Takes a moment to answer, as a real model does, so concurrent ingests interleave."""
    async def complete(self, lane, system, user, out):
        await asyncio.sleep(0.02)
        return await super().complete(lane, system, user, out)


def by_document(**facts_by_document):
    """A fake Intake model scripted with each Document's facts (named for readability): Intake reads one page at a
    time, and each page is answered with the scripted facts quoted on it, naming their Region (intake_reading)."""
    return SlowFakeLLM(intake_reading([f for facts in facts_by_document.values() for f in facts]))


@pytest.fixture
def documents_ctx(clean_db, tmp_path):
    fake = by_document(referral=REFERRAL_FACTS, Pathology=BLOODS_FACTS)
    ctx = make_ctx(clean_db, fake, parser=recorded(*PARSE))
    return replace(ctx, settings=Settings(_env_file=None, pg_dsn=ADMIN_DSN, raw_documents_dir=str(tmp_path)))


async def _patient_with_questionnaire(ctx) -> record.PatientId:
    patient = await record.create_patient(ctx, "Demo patient U")
    outcome = await record.submit_questionnaire(ctx, patient, {"sex": "female"}, respondent="patient")
    assert isinstance(outcome, record.Committed) and outcome.version.number == 1
    return patient


async def test_an_added_pdf_becomes_a_document_with_deidentified_pages_and_creates_the_next_version(documents_ctx):
    ctx = documents_ctx
    patient = await _patient_with_questionnaire(ctx)

    registered = await record.register_document(ctx, patient, "referral.pdf", REFERRAL)
    outcome = await ingest_as_read(ctx, registered.document.hash)

    assert registered.deduplicated is False
    stored = await record.document(ctx, registered.document.hash)
    assert (stored.patient_id, stored.filename, len(stored.pages)) == (patient, "referral.pdf", 2)
    assert "Oncology referral letter" in stored.pages[0].text and "[PATIENT]" in stored.pages[0].text
    for identifier in IDENTIFIERS:
        assert identifier not in "\n".join(p.text for p in stored.pages)
        assert identifier not in "\n".join(c.user for c in ctx.llm.calls)

    assert isinstance(outcome, record.Committed) and outcome.version.number == 2
    version = await record.profile_version(ctx, outcome.version.id)
    cancer = next(f for f in version.facts if f.subject == "breast cancer")
    assert (cancer.document_hash, cancer.page, cancer.observed_on, cancer.question) == (
        registered.document.hash, 2, date(2024, 3, 12), None)
    assert {f.subject for f in version.facts} >= {"sex assigned at birth", "breast cancer", "ecog"}


async def test_adding_the_same_bytes_twice_is_deduplicated(documents_ctx):
    ctx = documents_ctx
    patient = await _patient_with_questionnaire(ctx)
    first = await record.register_document(ctx, patient, "referral.pdf", REFERRAL)
    committed = await ingest_as_read(ctx, first.document.hash)

    again = await record.register_document(ctx, patient, "referral (1).pdf", REFERRAL)
    outcome = await ingest_as_read(ctx, again.document.hash)

    assert again.deduplicated is True and again.document.hash == first.document.hash
    assert (await record.document(ctx, again.document.hash)).filename == "referral.pdf"
    assert isinstance(outcome, record.Committed) and outcome.version == committed.version
    assert outcome.run_id == committed.run_id
    assert len(ctx.llm.calls) == 2, "one Intake call for each of its two pages, the first time only"
    assert (await record.current_version(ctx, patient)).number == 2


async def test_the_same_bytes_from_two_patients_are_two_documents(documents_ctx):
    ctx = documents_ctx
    a, b = await _patient_with_questionnaire(ctx), await _patient_with_questionnaire(ctx)

    from_a = await record.register_document(ctx, a, "referral.pdf", REFERRAL)
    from_b = await record.register_document(ctx, b, "referral.pdf", REFERRAL)

    assert from_b.deduplicated is False and from_b.document.hash != from_a.document.hash
    assert (await record.document(ctx, from_b.document.hash)).patient_id == b
    assert (await ingest_as_read(ctx, from_b.document.hash)).version.patient_id == b


async def test_several_documents_added_at_once_create_one_version_each(documents_ctx):
    ctx = documents_ctx
    patient = await _patient_with_questionnaire(ctx)
    referral = await record.register_document(ctx, patient, "referral.pdf", REFERRAL)
    bloods = await record.register_document(ctx, patient, "bloods.pdf", BLOODS)

    outcomes = await asyncio.gather(ingest_as_read(ctx, referral.document.hash), ingest_as_read(ctx, bloods.document.hash))

    assert all(isinstance(o, record.Committed) for o in outcomes)
    assert sorted(o.version.number for o in outcomes) == [2, 3]
    latest = await record.current_version(ctx, patient)
    assert latest.number == 3
    assert {"sex assigned at birth", "breast cancer", "ecog", "haemoglobin"} <= {f.subject for f in latest.facts}


async def test_a_file_without_readable_text_is_refused_before_anything_is_stored(documents_ctx):
    ctx = documents_ctx
    patient = await _patient_with_questionnaire(ctx)

    for content in (b"GIF89a not a pdf", BLANK):
        with pytest.raises(record.UnreadableDocument):
            await record.register_document(ctx, patient, "scan.pdf", content)

    assert (await record.current_version(ctx, patient)).number == 1
    assert ctx.llm.calls == []


async def test_two_patients_adding_documents_at_the_same_time_each_get_their_next_version(documents_ctx):
    ctx = documents_ctx
    a, b = await _patient_with_questionnaire(ctx), await _patient_with_questionnaire(ctx)
    from_a = await record.register_document(ctx, a, "referral.pdf", REFERRAL)
    from_b = await record.register_document(ctx, b, "bloods.pdf", BLOODS)

    outcomes = await asyncio.gather(ingest_as_read(ctx, from_a.document.hash), ingest_as_read(ctx, from_b.document.hash))

    assert [(o.version.patient_id, o.version.number) for o in outcomes] == [(a, 2), (b, 2)]
