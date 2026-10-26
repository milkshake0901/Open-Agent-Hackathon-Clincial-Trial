"""A trial answer may cite only regions on the letter, and only exclusion lines stored on the trial."""
from datetime import date

from app.matching.letter import _Ask, _Miss, ground_ask
from app.record import LetterSpan
from app.trials import Criterion, CriterionId, CriterionKind, NctId

SPAN = LetterSpan(
    id="letter:p1:b1", document_hash="abc", filename="referral.pdf", page=1, kind="Text",
    text="He received Lu-177 from June to November 2023.", x0=0.1, y0=0.2, x1=0.8, y1=0.3,
)
EXCLUSION = Criterion(
    id=CriterionId("NCT1:abcd:3"), nct_id=NctId("NCT1"), eligibility_hash="abcd", kind=CriterionKind.EXCLUSION,
    ordinal=3, text="Prior treatment with Lutetium-177 or another PSMA-targeted radioligand.",
)
INCLUSION = Criterion(
    id=CriterionId("NCT1:abcd:1"), nct_id=NctId("NCT1"), eligibility_hash="abcd", kind=CriterionKind.INCLUSION,
    ordinal=1, text="Histologically confirmed adenocarcinoma of the prostate.",
)


def test_an_invented_region_cannot_make_the_patient_eligible():
    asked = ground_ask("NCT1", "A trial", "Am I eligible?", (SPAN,), (EXCLUSION,), _Ask(
        standing="eligible", answer="He meets it.", span_ids=["no-such-region"]), "zetaris", today=date(2026, 10, 26))
    assert asked.standing == "needs_information"
    assert asked.citations == ()
    assert asked.via == "zetaris"


def test_a_real_region_is_kept():
    asked = ground_ask("NCT1", "A trial", "What does the letter show?", (SPAN,), (), _Ask(
        standing="possible", answer="The letter shows Lu-177.", span_ids=["letter:p1:b1"],
        to_gather=["Recent scans"]), "postgres", today=date(2026, 10, 26))
    assert "Lu-177" in asked.citations[0].quote
    assert asked.to_gather == ("Recent scans",)


def test_an_exclusion_is_kept_only_when_the_line_is_verbatim_and_the_region_is_real():
    asked = ground_ask("NCT1", "A trial", "Am I eligible?", (SPAN,), (EXCLUSION, INCLUSION), _Ask(
        standing="excluded", answer="Prior radioligand rules this out.", misses=[
            _Miss(criterion_id="NCT1:abcd:3", clause="Prior treatment with Lutetium-177",
                  span_id="letter:p1:b1", why="The letter records Lu-177."),
            _Miss(criterion_id="NCT1:abcd:1", clause="Histologically confirmed adenocarcinoma",
                  span_id="letter:p1:b1", why="An inclusion is not an exclusion."),
            _Miss(criterion_id="NCT1:abcd:3", clause="a line that is not in the criterion",
                  span_id="letter:p1:b1", why="Invented."),
            _Miss(criterion_id="no-such", clause="Prior treatment with Lutetium-177",
                  span_id="letter:p1:b1", why="Invented id."),
        ]), "zetaris", today=date(2026, 10, 26))
    assert len(asked.misses) == 1
    assert asked.misses[0].clause == "Prior treatment with Lutetium-177"
    assert asked.misses[0].citation.span_id == "letter:p1:b1"


def test_a_washout_the_clock_has_passed_is_not_listed_as_an_exclusion():
    span = LetterSpan(
        id="letter:p2:b4", document_hash="abc", filename="referral.pdf", page=2, kind="Text",
        text="Terbium-161 treatment from Feb 2025 to September 2025.", x0=0.1, y0=0.4, x1=0.9, y1=0.5,
    )
    criterion = Criterion(
        id=CriterionId("NCT07213674:abcd:8"), nct_id=NctId("NCT07213674"), eligibility_hash="abcd",
        kind=CriterionKind.EXCLUSION, ordinal=8,
        text="Prior radioligand therapy (RLT) within 8 weeks of first dose of study treatment.",
    )
    asked = ground_ask("NCT07213674", "Xaluritamig", "Am I eligible?", (span,), (criterion,), _Ask(
        standing="excluded", answer="Prior radioligand rules this out.", misses=[
            _Miss(criterion_id="NCT07213674:abcd:8", clause="within 8 weeks of first dose",
                  span_id="letter:p2:b4", why="The letter records Terbium-161."),
        ]), "zetaris", today=date(2026, 10, 26))
    assert asked.misses == ()
    assert asked.standing == "possible"
    assert asked.washouts[0].cleared
    assert asked.washouts[0].last_on == date(2025, 9, 30)
