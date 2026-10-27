"""A finished letter fills the questionnaire answers its Facts support."""
from app.record.letter_details import from_drafts


def test_a_letter_fills_diagnosis_treatments_and_current_medicines():
    answers = from_drafts([
        {"resource": "Condition", "subject": "prostate cancer", "value": "metastatic prostate cancer",
         "observed_on": "2017-02-09"},
        {"resource": "Procedure", "subject": "radiotherapy", "value": "tomotherapy 76 Gy",
         "observed_on": "2017-05-01"},
        {"resource": "MedicationStatement", "subject": "docetaxel", "value": "stopped",
         "observed_on": "2019-01-15"},
        {"resource": "MedicationStatement", "subject": "enzalutamide", "value": "40 mg", "unit": "daily",
         "observed_on": "2026-02-09"},
        {"resource": "Patient", "subject": "sex assigned at birth", "value": "Male"},
        {"resource": "AllergyIntolerance", "subject": "penicillin", "value": "absent"},
        {"resource": "Observation", "subject": "psa", "value": "4.2", "unit": "ng/mL"},
    ])

    assert answers["diagnosis"] == "metastatic prostate cancer"
    assert answers["diagnosis_when"] == "9 February 2017"
    assert "tomotherapy 76 Gy (1 May 2017)" in answers["treatments"]
    assert "docetaxel: stopped (15 January 2019)" in answers["treatments"]
    assert answers["medicines"] == "enzalutamide: 40 mg daily (9 February 2026)"
    assert answers["sex"] == "male"
    assert answers["has_allergies"] == "no"
    assert "psa" not in answers["diagnosis"]
    assert "postcode" not in answers


def test_a_named_allergy_is_a_yes():
    answers = from_drafts([
        {"resource": "AllergyIntolerance", "subject": "penicillin", "value": "rash"},
    ])
    assert answers == {"has_allergies": "yes", "allergies": "penicillin: rash"}
