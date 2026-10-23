# TrialMatch

Matches one patient's scattered clinical documents against ClinicalTrials.gov eligibility criteria, explaining every verdict with citations, and re-checks whenever the patient's record changes.

## Patient record

**Document**:
One source file the patient supplies (referral letter, blood report, genomic report), identified by the hash of its content.
_Avoid_: File, upload, record, PDF

**Fact**:
One dated clinical statement taken from a Document, such as a diagnosis, a lab value or a medication, always pointing back to its Document and page.
_Avoid_: Data point, observation (unless meaning the FHIR resource), extraction

**Observed-on date**:
The date a Fact was true in the patient's life, as opposed to when its Document was uploaded.
_Avoid_: Date, timestamp, upload date

**Conflict**:
Two Facts that cannot both be true: same subject and observed-on date with different values, or an impossible sequence such as an age going backwards.
_Avoid_: Error, inconsistency, mismatch

**Profile version**:
The patient's set of accepted Facts after a Document is accepted; each accepted Document creates a new one and earlier versions are kept.
_Avoid_: Profile (unqualified), snapshot, patient state

**De-identification**:
Removing names, addresses, record numbers and clinician names from a Document's text before any model sees it.
_Avoid_: Anonymisation, redaction, masking

## Trials

**Trial**:
A study registered on ClinicalTrials.gov, identified by its NCT ID.
_Avoid_: Study, protocol

**Criterion**:
One inclusion or exclusion rule taken from a Trial's eligibility text.
_Avoid_: Requirement, condition, rule

## Matching

**Criterion result**:
The outcome of one Criterion against one Profile version: met, not met or unknown, citing the Fact it relied on.
_Avoid_: Check, finding

**Verdict**:
The overall outcome of one Trial against one Profile version: eligible, possible or excluded.
_Avoid_: Match, score, result

**Citation**:
The link from a claim in a Criterion result back to a Fact, and through it to a Document and page.
_Avoid_: Reference, source, evidence link

**Doctor question**:
A question for the patient's clinician, generated from a Criterion result that is unknown because no Fact covers it.
_Avoid_: Follow-up, gap, missing info

**Re-scan**:
Re-running matching for every cached Trial against a new Profile version.
_Avoid_: Refresh, re-run, recheck
