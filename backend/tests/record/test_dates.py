"""Dates follow the Document (#47): its date order, its Document date, and relative dates counted back from it.
Pure rules (app.record.dates), no I/O. Every date and phrase here is invented."""
from __future__ import annotations

from datetime import date

from app.record import dates


def test_a_date_with_a_day_over_12_first_makes_the_document_day_first():
    assert dates.date_order(["PSA 3.4 on 4/9/23", "seen 23/11/23"]) == "day_first"


def test_a_date_with_a_day_over_12_second_makes_the_document_month_first():
    assert dates.date_order(["seen 11/23/2023", "biopsy 2/7/23"]) == "month_first"


def test_a_document_whose_dates_all_read_both_ways_has_no_date_order():
    assert dates.date_order(["biopsy 7/2/23", "scan 3/4/2023", "02 October 2026", "2026-10-02"]) is None


def test_dates_that_disagree_give_no_date_order():
    assert dates.date_order(["23/11/23", "11/23/23"]) is None


def test_fractions_and_blood_pressures_are_not_dates():
    assert dates.date_order(["blood pressure 142/86", "Gleason 4+4=8", "page 1 of 3"]) is None


def test_a_numeric_date_is_read_in_the_documents_order():
    [read] = dates.dates_in("diagnosed on TRUS biopsy 7/2/23", "day_first")
    assert (read.on, read.ambiguous) == (date(2023, 2, 7), False)
    [read] = dates.dates_in("diagnosed on TRUS biopsy 7/2/23", "month_first")
    assert read.on == date(2023, 7, 2)


def test_with_no_date_order_a_date_that_reads_both_ways_is_ambiguous_and_read_day_first():
    [read] = dates.dates_in("PET on 7/2/23", None)
    assert (read.on, read.ambiguous, read.other) == (date(2023, 2, 7), True, date(2023, 7, 2))


def test_a_date_with_the_same_day_and_month_or_a_day_over_12_is_never_ambiguous():
    assert [(r.on, r.ambiguous) for r in dates.dates_in("5/5/23 and 23/11/2023", None)] == [
        (date(2023, 5, 5), False), (date(2023, 11, 23), False)]


def test_written_out_and_iso_dates_read_only_one_way():
    found = dates.dates_in("02 October 2026; Oct 3, 2026; 2026-10-04; 5th Jan 2025", None)
    assert [(r.on, r.ambiguous) for r in found] == [
        (date(2026, 10, 2), False), (date(2026, 10, 3), False), (date(2026, 10, 4), False), (date(2025, 1, 5), False)]


def test_a_date_that_does_not_exist_is_not_read():
    assert dates.dates_in("31/2/23", "day_first") == ()


def test_a_reports_document_date_is_its_service_date_not_the_date_it_was_reported():
    page_one = ["Lakeshore Imaging", "| DOB | [DOB]|\n| Date of service | 02 October 2026 |", "MRI LEFT KNEE",
                "Reported by [CLINICIAN-2], 03 October 2026"]
    read = dates.document_date(page_one, None)
    assert (read.text, read.on, read.ambiguous) == ("02 October 2026", date(2026, 10, 2), False)


def test_a_letters_document_date_is_the_date_it_was_dictated_read_in_its_date_order():
    page_one = ["Department of Uro-oncology", "Dictated: 2/11/23\nTyped: 7/11/23", "biopsy 7/2/23"]
    assert dates.document_date(page_one, "day_first").on == date(2023, 11, 2)
    assert dates.document_date(page_one, "month_first").on == date(2023, 2, 11)


def test_with_no_labelled_date_the_document_date_is_the_first_date_on_the_first_page():
    assert dates.document_date(["Clinic letter", "Seen in clinic 14 March 2025.", "PSA 4 on 2/1/2025"],
                               None).on == date(2025, 3, 14)


def test_a_first_page_with_no_date_has_no_document_date():
    assert dates.document_date(["Clinic letter", "DOB: [DOB]"], None) is None


def test_an_ambiguous_document_date_is_kept_flagged():
    read = dates.document_date(["Date: 3/4/25"], None)
    assert (read.on, read.ambiguous) == (date(2025, 4, 3), True)


def test_a_relative_date_is_counted_back_from_the_document_date():
    on = date(2026, 10, 2)
    assert dates.relative_date("Twisting injury playing netball 4 months ago.", on) == date(2026, 6, 2)
    assert dates.relative_date("fell two weeks ago", on) == date(2026, 9, 18)
    assert dates.relative_date("surgery a year ago", on) == date(2025, 10, 2)
    assert dates.relative_date("started 3 days ago", on) == date(2026, 9, 29)


def test_counting_back_months_lands_on_the_last_day_of_a_shorter_month():
    assert dates.relative_date("1 month ago", date(2026, 3, 31)) == date(2026, 2, 28)


def test_a_text_with_no_relative_date_has_none():
    assert dates.relative_date("ACL tear on 02 October 2026", date(2026, 10, 2)) is None


REPORT = dates.Dating(order=None, document_date=dates.DateRead("02 October 2026", 0, date(2026, 10, 2)))
LETTER = dates.Dating(order="day_first", document_date=dates.DateRead("23/11/23", 0, date(2023, 11, 23)))


def test_a_fact_with_no_date_of_its_own_is_observed_on_the_document_date():
    assert dates.observed_on(None, "Menisci: No meniscal tear.", REPORT) == (date(2026, 10, 2), ("document_date",))


def test_a_relative_date_is_a_flagged_estimate_whatever_date_the_model_gave():
    quote = "Twisting injury playing netball 4 months ago."
    assert dates.observed_on(date(2026, 10, 2), quote, REPORT) == (date(2026, 6, 2), ("estimated_date",))


def test_a_date_the_model_left_out_is_read_from_the_quote_in_the_documents_order():
    assert dates.observed_on(None, "PET on 7/2/23", LETTER) == (date(2023, 2, 7), ())


def test_the_models_date_stands_and_an_ambiguous_one_is_flagged():
    assert dates.observed_on(date(2023, 2, 7), "PET on 7/2/23", LETTER) == (date(2023, 2, 7), ())
    no_order = dates.Dating(order=None, document_date=None)
    assert dates.observed_on(date(2023, 7, 2), "PET on 7/2/23", no_order) == (date(2023, 7, 2), ("ambiguous_date",))
    assert dates.observed_on(None, "PET on 7/2/23", no_order) == (date(2023, 2, 7), ("ambiguous_date",))


def test_with_no_date_anywhere_a_fact_has_no_observed_on_date():
    assert dates.observed_on(None, "Hypertension", dates.Dating(order=None, document_date=None)) == (None, ())


def test_a_documents_dating_comes_from_all_its_pages_and_its_first_page():
    from app.record.types import Document, Page
    doc = Document(hash="h", patient_id="p", filename="f.pdf", uploaded_at=date(2026, 10, 24), pages=(
        Page(1, "Clinic letter\nDate: 3/4/25\nbiopsy 7/2/23"), Page(2, "PSA 4 on 20/3/25")))
    found = dates.dating(doc)
    assert (found.order, found.document_date.on, found.document_date.ambiguous) == ("day_first", date(2025, 4, 3), False)
