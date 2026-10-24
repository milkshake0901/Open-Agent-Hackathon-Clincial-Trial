# TrialMatch

Matches one patient's scattered clinical documents against ClinicalTrials.gov eligibility criteria, explaining every verdict with citations, and re-checks whenever the patient's record changes.

## Patient record

**Intake questionnaire**:
The plain-language questions a Respondent answers on first contact (age, sex, diagnosis in their own words, treatments, medicines); a completed one is itself a Document.
_Avoid_: Intake (unqualified, which means the agent that drafts Facts from a Document), form, onboarding

**Respondent**:
The person who answers the Intake questionnaire: the patient, or a family member or carer on their behalf.
_Avoid_: User, patient (when someone else is answering)

**Document**:
One source the patient supplies (referral letter, blood report, genomic report, or a completed Intake questionnaire), identified by the hash of its content.
_Avoid_: File, upload, record, PDF

**Patient-reported**:
Describes a Fact whose Document is a completed Intake questionnaire rather than a clinical document.
_Avoid_: Self-reported, unverified, user-entered

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

**Criterion topic**:
A kind of patient information a Criterion asks about, such as performance status or CNS metastases; one Criterion can have several.
_Avoid_: Category, tag, bucket

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
A question for the patient's clinician, generated from a Criterion result that is unknown because no Fact covers it and answering needs clinical records or judgement (performance status, labs, stage).
_Avoid_: Follow-up, gap, missing info

**Respondent question**:
A question sent back to the Respondent when a Criterion result turns on something they could plausibly know (a date, a medicine name) but answered too vaguely or not at all.
_Avoid_: Follow-up, clarification, Doctor question

**Re-scan**:
Re-running matching for every cached Trial against a new Profile version.
_Avoid_: Refresh, re-run, recheck
