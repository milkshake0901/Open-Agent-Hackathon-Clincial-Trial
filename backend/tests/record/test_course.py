"""A letter's treatments become a dated timeline, and PSA is the marker set beside prostate cancer."""
from datetime import date

from app.record.course import Comparison, Note, Row, Treatment, build, ground, merge_groups


def _row(resource, subject, value, on, unit=None):
    return Row(resource, subject, value, unit, date.fromisoformat(on) if on else None)


def test_prostate_treatments_are_ordered_and_psa_is_the_marker():
    course = build([
        _row("Condition", "prostate cancer", "metastatic prostate cancer", "2017-02-09"),
        _row("Procedure", "radiotherapy", "tomotherapy 76 Gy", "2017-06-01"),
        _row("MedicationStatement", "docetaxel", "stopped", "2019-01-15"),
        _row("Observation", "psa", "33", "2017-02-01", "ng/mL"),
        _row("Observation", "psa", "4.2", "2026-02-06", "ng/mL"),
        _row("Observation", "haemoglobin", "11.2", "2026-02-06", "g/dL"),
        _row("Observation", "psma pet", "no evidence of disease", "2021-05-01"),
        _row("MedicationStatement", "olaparib", "started", None),
    ], "metastatic prostate cancer")

    assert [item.subject for item in course.treatments] == ["radiotherapy", "docetaxel", "olaparib"]
    assert course.treatments[-1].on is None
    assert course.marker == "PSA"
    assert [point.number for point in course.series[0].points] == [33.0, 4.2]
    assert course.series[0].points[0].unit == "ng/mL"


def test_a_comparison_note_has_to_name_a_real_treatment_and_a_real_reading():
    course = build([
        _row("Procedure", "docetaxel", "6 cycles", "2019-01-15"),
        _row("Observation", "psa", "12", "2019-02-01"),
    ], "prostate cancer")
    compared = ground(course, "PSA fell after docetaxel.", [
        Note("docetaxel", "2019-02-01", "12", "lower than before"),
        Note("docetaxel", "2020-01-01", "1", "invented"),
        Note("abiraterone", "2019-02-01", "12", "not on the letter"),
    ])

    assert compared.summary == "PSA fell after docetaxel."
    assert compared.notes == (Note("docetaxel", "2019-02-01", "12", "lower than before"),)
    assert isinstance(compared, Comparison)


def test_the_judge_groups_only_same_day_rows_that_it_names_together():
    day = date(2024, 7, 8)
    other = date(2023, 5, 1)
    items = (
        Treatment("xtandi", "Xtandi continued with Enantone until May 2023", other),
        Treatment("xtandi", "Xtandi continued with Enantone", other),
        Treatment("cabazitaxel", "cabazitaxel", day),
        Treatment("bone biopsy", "Bone biopsy performed confirming metastatic adenocarcinoma", day),
        Treatment("bone biopsy", "Bone biopsy performed", day),
        Treatment("chemotherapy with cabazitaxel", "4 cycles of cabazitaxel", day),
    )

    merged = merge_groups(items, [[0, 1], [2, 5], [3, 4]])

    assert [(item.subject, item.on) for item in merged] == [
        ("xtandi", other), ("chemotherapy with cabazitaxel", day), ("bone biopsy", day)]
    assert merged[0].detail == "Xtandi continued with Enantone until May 2023"
    assert merged[2].detail == "Bone biopsy performed confirming metastatic adenocarcinoma"
    assert merge_groups(items, [[0, 2]]) == items
