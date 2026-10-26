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

**Region**:
One block of text on a Document page, with its position on that page, that a Fact can quote.
_Avoid_: Span, block, box, bbox

**Letter review**:
The optional step where the Respondent looks at each Fact drafted from a letter beside its Region and keeps or drops it before it enters the record.
_Avoid_: Verification, approval, check

**Patient-reported**:
Describes a Fact whose Document is a completed Intake questionnaire rather than a clinical document.
_Avoid_: Self-reported, unverified, user-entered

**Fact**:
One dated clinical statement taken from a Document, such as a diagnosis, a lab value or a medication, always pointing back to its Document and page.
_Avoid_: Data point, observation (unless meaning the FHIR resource), extraction

**Observed-on date**:
The date a Fact was true in the patient's life, as opposed to when its Document was uploaded.
_Avoid_: Date, timestamp, upload date

**Document date**:
The date a Document was written or a test was done, as the Document states it; the Observed-on date of any Fact that gives no date of its own, and the point "4 months ago" is counted back from.
_Avoid_: Upload date, letter date, service date

**Conflict**:
Two Facts that cannot both be true: same subject and observed-on date with different values, or an impossible sequence such as an age going backwards.
_Avoid_: Error, inconsistency, mismatch

**Profile version**:
The patient's set of accepted Facts after a Document is accepted; each accepted Document creates a new one and earlier versions are kept.
_Avoid_: Profile (unqualified), snapshot, patient state

**De-identification**:
Removing names, addresses, record numbers, dates of birth and clinician names from a Document's page text, Region text and filename, in one pass over the whole Document, before it is stored or any model sees it. Region boxes are kept.
_Avoid_: Anonymisation, redaction, masking

**Return link**:
A private link the Respondent receives after their first Intake questionnaire that reopens that patient's record without an account.
_Avoid_: Login, magic link, account

**Search preferences**:
The patient's postcode, how far they would travel and an optional contact detail; used only to rank Trials by distance and send notices, never part of the patient's Facts.
_Avoid_: Settings, location Fact, profile

**Diagnosis check**:
The step where the Respondent is shown a shortlist of Condition labels that fit their diagnosis in their own words, and ticks the ones that match, or answers none of these or not sure.
_Avoid_: Diagnosis confirmation, normalisation

**Condition label**:
One condition exactly as a Trial lists it on ClinicalTrials.gov, such as "Anterior Cruciate Ligament Rupture"; a Diagnosis check only ever offers labels some Trial uses.
_Avoid_: Condition (unqualified), keyword, tag

**Condition term**:
The set of Condition labels the Respondent ticked in their latest Diagnosis check; it selects the Open trials that are judged and the Closed trials that are shown. Until a patient has one, no Trial is judged.
_Avoid_: Search term, diagnosis code, diagnosis

## Trials

**Trial**:
A study registered on ClinicalTrials.gov with at least one Trial site in Australia, identified by its NCT ID; studies with no Australian site are out of scope.
_Avoid_: Study, protocol

**Open trial**:
A Trial that is recruiting, not yet recruiting or enrolling by invitation; only Open trials are judged and get Verdicts.
_Avoid_: Active trial, live trial

**Closed trial**:
A Trial that can no longer enrol (completed, terminated, suspended, active-not-recruiting or unknown) and finished within the last 15 years; shown to the patient for its outcomes and contacts, never judged. Withdrawn studies are not Trials, nor are expanded access records (available, no longer available).
_Avoid_: Past study, old trial, inactive trial

**Outcome**:
What a Trial measured or found: its planned outcome measures, any posted results, and linked publications.
_Avoid_: Result (unqualified), finding, endpoint

**Criterion**:
One inclusion or exclusion rule taken from a Trial's eligibility text.
_Avoid_: Requirement, condition, rule

**Criterion topic**:
A kind of patient information a Criterion asks about, such as performance status or CNS metastases; one Criterion can have several.
_Avoid_: Category, tag, bucket

**Trial site**:
One Australian place a Trial runs, with its recruitment status and location (sites in other countries are not kept); distance to it ranks Trials but never changes a Verdict.
_Avoid_: Location, centre, facility

## Matching

**Criterion result**:
The outcome of one Criterion against one Profile version: met, not met or unknown, citing the Fact it relied on.
_Avoid_: Check, finding

**Verdict**:
The overall outcome of one Trial against one Profile version: eligible, possible or excluded.
_Avoid_: Match, score, result

**Citation**:
The link from a claim in a Criterion result back to a Fact, and through it to a Document and page; for a letter, to the Region the Fact was read from, and for an Intake questionnaire, to the answer it quotes.
_Avoid_: Reference, source, evidence link

**Context Fact**:
A Fact an unknown Criterion result considered but that does not settle it, such as a hormone therapy named when the needed testosterone level is missing; shown beside the reason, never counted as a Citation.
_Avoid_: Partial citation, evidence, related fact

**Doctor question**:
A question for the patient's clinician, generated from a Criterion result that is unknown because no Fact covers it and answering needs clinical records or judgement (performance status, labs, stage).
_Avoid_: Follow-up, gap, missing info

**Respondent question**:
A question sent back to the Respondent when a Criterion result turns on something they could plausibly know (a date, a medicine name) but answered too vaguely or not at all.
_Avoid_: Follow-up, clarification, Doctor question

**Enquiry**:
An email body drafted for the Respondent to edit, copy and send themselves to a Trial's contact: for an Open trial it asks about taking part, for a Closed trial about its Outcomes or a follow-on study. The app never sends it, and it holds only the clinical details the Respondent kept ticked.
_Avoid_: Message, contact request, email (unqualified)

**Re-scan**:
Re-running matching for every Open trial the patient's Condition term selects against a Profile version, run when the Respondent or an operator asks; an ingest never triggers one.
_Avoid_: Refresh, re-run, recheck
