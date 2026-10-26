"""A washout is measured from the letter's dates to today. The model does not do the subtraction."""
from datetime import date

from app.matching.clock import dates_in, measure, window_days
from app.record import LetterSpan
from app.trials import Criterion, CriterionId, CriterionKind, NctId

TODAY = date(2026, 10, 26)


def _span(text: str, span_id: str = "letter:p2:b1") -> LetterSpan:
    return LetterSpan(id=span_id, document_hash="abc", filename="referral.pdf", page=2, kind="Text",
                      text=text, x0=0.1, y0=0.2, x1=0.9, y1=0.4)


def _exclusion(text: str, ordinal: int = 1) -> Criterion:
    return Criterion(id=CriterionId(f"NCT07213674:abcd:{ordinal}"), nct_id=NctId("NCT07213674"),
                     eligibility_hash="abcd", kind=CriterionKind.EXCLUSION, ordinal=ordinal, text=text)


def test_dates_use_day_month_year_and_the_end_of_a_named_month():
    assert dates_in("Lu-177 from 1/6/23 to 23/11/23") == (date(2023, 6, 1), date(2023, 11, 23))
    assert dates_in("Terbium-161 from Feb 2025 to September 2025") == (date(2025, 2, 28), date(2025, 9, 30))
    assert dates_in("radiotherapy 3 Feb 2026") == (date(2026, 2, 3),)


def test_a_window_is_the_longest_interval_named():
    text = ("Any anticancer therapy within 4 weeks before first dose. "
            "Androgen receptor pathway inhibitors: minimum washout of 2 weeks prior to the first dose.")
    assert window_days(text) == 28
    assert window_days("Prior radioligand therapy (RLT) within 8 weeks of first dose of study treatment.") == 56
    assert window_days("Prior chemotherapy regimen in the mCRPC setting.") is None


def test_an_old_radioligand_is_outside_an_eight_week_window():
    spans = (
        _span("He went on to receive 4 dose of Lu-177 treatment from 1/6/23 to 23/11/23.", "lu"),
        _span("Patient also received multiple course of Terbium-161 treatment from Feb 2025 to September 2025.", "tb"),
    )
    rows = measure((
        _exclusion("Prior radioligand therapy (RLT) within 8 weeks of first dose of study treatment.", 1),
        _exclusion("Prior treatment with any chemotherapy regimen in the mCRPC setting.", 2),
    ), spans, TODAY)
    assert len(rows) == 1
    assert rows[0].last_on == date(2025, 9, 30)
    assert rows[0].days_before > 56
    assert rows[0].cleared
    assert rows[0].span_id == "tb"


def test_a_dose_inside_the_window_is_not_cleared():
    spans = (_span("Cabazitaxel was given on 19/10/26."),)
    rows = measure((_exclusion("Any anticancer therapy within 4 weeks before first dose of study treatment."),),
                   spans, TODAY)
    assert rows[0].last_on == date(2026, 10, 19)
    assert rows[0].cleared is False
