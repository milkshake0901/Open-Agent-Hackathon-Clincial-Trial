"""Intake answers are copied from a referral's parsed regions, and only from those words."""
from app.record.prefill import prefill_answers

LETTER = [
    ("Title", "Re: BRADLEY, MARTIN Age:55 Sex:M P376054(9)"),
    ("Text", "Mr Bradley has family history of prostate cancer with his father and brother both diagnosed "
             "with prostate cancer. Mr Bradley himself was diagnosed of prostate cancer during routine blood "
             "test which showed raised PSA to 33 in February 2017. TRUS biopsy showed adenocarcinoma in all "
             "subsites, Gleason score 9 (5+4)."),
    ("Text", "He also received ADT with Enantone starting in March 2017."),
    ("Text", "PET in December 2017 showed no abnormal uptake in prostate."),
    ("Text", "He is also on Xgeva and Enantone. His PSA was 147 on 6/2/26."),
    ("Text", "Chemo-immunotherapy was stopped after 3 cycles."),
    ("Text", "In summary, Mr Bradley has CRPC with extensive bone disease, failed NHA, PARP inhibitor, "
             "docetaxel, radioligand treatment and chemo-immunotherapy."),
    ("Caption", "Hong Kong Sanatorium & Hospital Limited"),
]


def test_prefill_uses_the_letter_and_leaves_out_what_it_does_not_say():
    answers = prefill_answers(LETTER)
    assert answers["respondent"] == "other"
    assert answers["sex"] == "male"
    assert answers["diagnosis_when"] == "February 2017"
    assert "castration-resistant" in answers["diagnosis"]
    assert "Gleason score 9 (5+4)" in answers["diagnosis"]
    assert "family history of prostate cancer" in answers["diagnosis"]
    assert "Enantone" in answers["treatments"]
    assert "no abnormal uptake" not in answers["treatments"]
    assert answers["medicines"].startswith("Xgeva and Enantone")
    assert "stopped" in answers["medicines"]
    assert "birth_month" not in answers
    assert "postcode" not in answers


def test_a_letter_with_no_clinical_text_fills_nothing():
    assert prefill_answers([("Caption", "Printed on 09/02/2026")]) == {}
