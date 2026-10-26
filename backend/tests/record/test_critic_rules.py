"""The Critic catches a model's mechanical misreads (#47): each is a retryable finding sent back to Intake.
critic.review is pure; the Document here is a hand-made letter read into Regions, every word invented."""
from __future__ import annotations

from datetime import date

from app.record import critic
from app.record.types import Document, DraftFact, FactResource, FindingKind, Page, Region

LINES = ("Dictated: 23/11/23", "Adenocarcinoma, Gleason 4+4=8, diagnosed on TRUS biopsy 7/2/23",
         "PSA 11.2 ng/mL on 20/11/23")
LETTER = Document(
    hash="letter", patient_id="pt", filename="letter.pdf", uploaded_at=date(2026, 10, 24),
    pages=(Page(1, "\n".join(LINES)),),
    regions=tuple(Region(f"letter:p1:b{i}", 1, i, "Text", text, 0.1, 0.1 * i, 0.9, 0.1 * i + 0.05)
                  for i, text in enumerate(LINES)))


def draft(subject, value, quote, span, on, unit=None):
    return DraftFact(resource=FactResource.OBSERVATION, subject=subject, value=value, unit=unit, observed_on=on,
                     page=1, quote=quote, span_id=f"letter:p1:b{span}")


def kinds(*drafts):
    findings = critic.review(drafts, LETTER, None)
    assert all(f.severity == "retryable" for f in findings)
    return [(f.kind, f.draft_index) for f in findings]


def test_a_letter_read_as_written_has_no_findings():
    assert kinds(draft("gleason score", "4+4=8", "Gleason 4+4=8", 1, date(2023, 2, 7)),
                 draft("psa", "11.2", "11.2 ng/mL on 20/11/23", 2, date(2023, 11, 20), unit="ng/mL")) == []


def test_a_quote_from_another_region_than_the_one_named_is_sent_back():
    assert kinds(draft("psa", "11.2", "11.2 ng/mL on 20/11/23", 1, date(2023, 11, 20))) == [
        (FindingKind.QUOTE_NOT_IN_REGION, 0)]


def test_a_number_in_the_value_that_is_not_in_the_quote_is_sent_back():
    assert kinds(draft("psa", "11.4", "11.2 ng/mL on 20/11/23", 2, date(2023, 11, 20)),
                 draft("psa", "1", "11.2 ng/mL on 20/11/23", 2, date(2023, 11, 20)),
                 draft("psa", "rising", "11.2 ng/mL on 20/11/23", 2, date(2023, 11, 20))) == [
        (FindingKind.NUMBER_NOT_IN_QUOTE, 0), (FindingKind.NUMBER_NOT_IN_QUOTE, 1)]


def test_a_date_read_against_the_documents_date_order_is_sent_back_with_the_right_reading():
    misread = draft("gleason score", "4+4=8", "Gleason 4+4=8, diagnosed on TRUS biopsy 7/2/23", 1, date(2023, 7, 2))
    [finding] = critic.review((misread,), LETTER, None)
    assert finding.kind == FindingKind.DATE_AGAINST_ORDER and finding.severity == "retryable"
    assert "7/2/23" in finding.message and "2023-02-07" in finding.message


def test_with_no_date_order_an_ambiguous_date_is_not_sent_back():
    no_order = Document(hash="d", patient_id="pt", filename="d.pdf", uploaded_at=date(2026, 10, 24),
                        pages=(Page(1, "biopsy 7/2/23"),),
                        regions=(Region("d:p1:b0", 1, 0, "Text", "biopsy 7/2/23", 0, 0, 1, 1),))
    d = DraftFact(resource=FactResource.PROCEDURE, subject="biopsy", value="done", unit=None,
                  observed_on=date(2023, 7, 2), page=1, quote="biopsy 7/2/23", span_id="d:p1:b0")
    assert critic.review((d,), no_order, None) == ()
