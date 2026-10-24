# Spec: Intake questionnaire

Labels: `ready-for-agent`

## Problem Statement

A patient, or a family member helping them, arrives wanting to know which clinical trials might fit. Today TrialMatch can only start from clinical Documents: they have to find and upload referral letters, blood reports and genomic reports before anything happens. Many Respondents don't have those to hand on day one, don't know which ones matter, and can't tell what the system already knows about them. Basic facts every Trial screens on (age, sex, diagnosis, treatments so far) are not in the Fact model at all, so even a well-documented patient gets avoidable unknowns. There is also no way for the system to come back to the Respondent when a Verdict turns on something only they can clarify, such as roughly when chemotherapy ended.

## Solution

On first contact the Respondent fills in an **Intake questionnaire**, like a first visit to a clinic: plain-language questions about the patient's age, sex, diagnosis in their own words, treatments, medicines, allergies, other illnesses, pregnancy, daily activity, and where they live and how far they would travel. Uploading clinical Documents is optional and can happen at the same time or any time later.

A completed Intake questionnaire is itself a **Document** (ADR 0003). Its answers become **Patient-reported** Facts through the same Critic and commit path as any other Document, so they are cited, versioned and checked against later Documents. The questionnaire alone creates Profile version 1 and starts a Re-scan, so the Respondent sees a first set of Verdicts within minutes. Each later upload adds a Profile version and the Verdicts update, showing what changed and why.

When a Criterion result turns on something the Respondent could clarify (a vague date, which medicine), the system sends a **Respondent question** back to them; things that need clinical records become Doctor questions, as today. The Respondent returns through a private link. Their postcode is used only by code to compute distances to trial sites: no model ever sees it. Trials are ranked by Verdict, then by nearest recruiting site; distance never changes a Verdict.

## User Stories

1. As a Respondent, I want to answer a short set of plain-language questions on first contact, so that I can get started without hunting for medical paperwork.
2. As a Respondent filling this in for a family member, I want to say that I am answering on their behalf, so that the questions are worded about them and readers know who answered.
3. As a Respondent, I want the questions to use "your" or "their" according to who I said is answering, so that the form reads naturally.
4. As a Respondent, I want to give the patient's birth year and month rather than a full date of birth, so that I share less identifying information.
5. As a Respondent, I want never to be asked for the patient's name or street address, so that I feel safe using the service.
6. As a Respondent, I want to answer "sex assigned at birth" with female, male, intersex or prefer not to say, so that I am not forced into an answer.
7. As a Respondent, I want to describe the diagnosis in my own words, so that I don't need to know the formal medical name.
8. As a Respondent, I want the system to show me how it understood the diagnosis ("We understood this as non-small cell lung cancer — is that right?") and let me answer yes, no or not sure, so that the search uses the right condition.
9. As a Respondent who is not sure of the diagnosis, I want to be told to check it with the GP, so that I know what to do next rather than being stuck.
10. As a Respondent, I want to give the year of diagnosis, so that Trials that depend on time since diagnosis can be judged.
11. As a Respondent, I want to list treatments so far in free text, with rough dates as I remember them ("chemo ended around March 2025"), so that I don't have to invent exact dates.
12. As a Respondent, I want to list current medicines, so that Trials that exclude certain medicines can be checked.
13. As a Respondent, I want to list allergies, so that Trials that exclude them can be checked.
14. As a Respondent, I want to list other major illnesses, so that comorbidity Criteria can be checked.
15. As a Respondent, I want to answer an optional "currently pregnant, breastfeeding or planning a pregnancy?" question with yes, no or prefer not to say, so that I can share it only if I'm comfortable.
16. As a Respondent, I want to answer one plain-language question about the patient's daily activity, so that performance-status Criteria get a patient-reported starting point.
17. As a Respondent, I want to give a postcode and how far the patient is willing to travel, so that nearby Trials are shown first.
18. As a Respondent, I want to skip any question I don't know, so that I can finish the form without guessing.
19. As a Respondent, I want to attach clinical Documents at the end of the questionnaire if I have them, so that matching is more complete from the start.
20. As a Respondent, I want to upload more Documents later, so that the result improves as I find paperwork.
21. As a Respondent, I want to see a first set of Trial Verdicts soon after submitting the questionnaire, even with no uploads, so that I get value straight away.
22. As a Respondent who attached several Documents at once, I want to see one "checking 3 documents…" progress indicator, so that I am not confused by several separate updates.
23. As a Respondent, I want to see which Verdicts changed after I uploaded a Document and why, so that I understand what each Document added.
24. As a Respondent, I want to correct an answer later, so that a mistake doesn't stick.
25. As a Respondent who corrected an answer, I want earlier Verdicts to stay visible as history, so that I can see what changed.
26. As a Respondent, I want to be asked when an answer I gave was too vague for a specific Trial to decide (a Respondent question), so that I can clarify it.
27. As a Respondent, I want Respondent questions listed separately from questions for the doctor, so that I know which ones I can answer myself.
28. As a Respondent, I want answering a Respondent question to update the Verdicts, so that my clarification counts.
29. As a Respondent, I want a list of Doctor questions to take to the patient's clinician, so that the appointment is productive.
30. As a Respondent, I want a private return link at the end of the questionnaire, so that I can come back without creating an account.
31. As a Respondent, I want to optionally leave an email or phone number for "you have new questions" notices, so that I don't have to keep checking.
32. As a Respondent, I want my contact details never to be seen by any model, so that my privacy is protected.
33. As a Respondent, I want to see the nearest recruiting site and its distance for each Trial, so that I can judge whether participating is practical.
34. As a Respondent, I want eligible Trials beyond my travel limit to still be visible under "Further away", so that I don't miss a Trial that might be worth the trip.
35. As a Respondent, I want a Verdict citation that came from my answers to say "Patient-reported, intake questionnaire, Q4", so that I can see where the system got it.
36. As a Respondent, when a clinical Document disagrees with something I answered (I said fully active, the referral letter says ECOG 2), I want to be asked which is right, so that the record is correct.
37. As a clinician reading a Verdict, I want to see which Facts are Patient-reported and who answered, so that I can judge how much to trust them.
38. As a clinician, I want Doctor questions to cover only what needs clinical records or judgement, so that I am not asked things the family could answer.
39. As the Matcher agent, I want each Trial's sites as "name, status, km", so that I can explain location without seeing the postcode.
40. As the Matcher agent, I want questionnaire Facts to carry the Respondent's verbatim words as the quote, so that I can tell when an answer is too vague for a Criterion.
41. As a developer, I want the questionnaire definition served by the backend independent of any channel, so that a WhatsApp or Telegram bot can later ask the same questions one at a time.
42. As a developer, I want structured answers mapped to Facts in code without calling a model, so that they are cheap, fast and exact.
43. As a developer, I want free-text answers to go through the existing Intake agent, so that there is one extraction path for prose.
44. As a developer, I want the Critic to accept best-estimate dates on Patient-reported Facts, so that approximate answers are not rejected as missing dates.
45. As a developer, I want resubmitting unchanged answers to add no new Facts, so that the record stays clean.
46. As a developer, I want age worked out at matching time from the birth month, so that it never goes stale across Profile versions.
47. As a demo audience member, I want to see "v1 from the questionnaire → v2 after the genomic report" with the Verdicts that changed, so that the value of the record growing is obvious.

## Implementation Decisions

**Record module**
- New public function `submit_questionnaire(ctx, patient_id, answers, respondent)`. It renders the answers to a Document (text, one page per section, each answer quoted with its question number), registers it like an upload (content hash, idempotent on identical bytes), and runs the existing ingest loop. It returns the same `IngestOutcome` union as `ingest` (Committed / AwaitingPatient / Rejected).
- The Respondent (patient, or family member or carer on their behalf) is a property of the submission, stored with the Document. It is not a Fact.
- Structured answers (birth year and month, sex, yes/no questions, the activity question) map to Facts deterministically in code. Free-text answers (diagnosis, treatments, medicines, allergies, other illnesses, approximate dates) go through the Intake agent. Both kinds then go through the Critic and the normal commit path through the World Model.
- Each Fact's quote is the Respondent's verbatim answer text and its page is the section page, so the existing quote-on-page check still applies.
- Observed-on date: for answers about the present (medicines, activity, pregnancy) it is the submission date. For answers that carry a date ("around March 2025"), the Intake agent stores its best-estimate date and keeps the verbatim quote. No precision field is added: the Matcher reads the quote to judge vagueness.
- The Critic no longer treats an approximate date as a missing date when the Document is an Intake questionnaire. All other checks, including Conflict detection against clinical Facts, apply unchanged.
- Correcting an answer, or answering a Respondent question, is a new full questionnaire submission: a new Document and Profile version. Unchanged answers are dropped as duplicates of accepted Facts.
- Two Fact resources are added, following the FHIR-lite naming: `Patient` (birth month, sex) and `AllergyIntolerance` (allergies). The fact table's resource check constraint is widened to match.
- Age is never stored; it is derived from the birth-month Fact when matching runs.
- The questionnaire alone produces Profile version 1, and a Re-scan follows on Committed, as for any Document.

**Questionnaire definition**
- The backend serves the questionnaire as data: questions, sections, answer types, optionality, and the "your"/"their" wording variants. The web UI renders it. Nothing in the definition assumes a page-based form, so a chat bot can ask it one question at a time later.
- Questions: who is answering; birth year and month; sex assigned at birth (female / male / intersex / prefer not to say); diagnosis in own words; year of diagnosis; treatments so far with rough dates; current medicines; allergies; other major illnesses; optional pregnancy, breastfeeding or planning a pregnancy (yes / no / prefer not to say); one plain-language daily-activity question; postcode; maximum travel distance. Every question can be skipped.
- Not asked: name, full date of birth, street address, labs, biomarkers, stage, histology, contraception. Those come from Documents or become Doctor questions.

**Diagnosis normalisation**
- After submission, a model proposes a condition term for the free-text diagnosis. The Respondent confirms it with yes / no / not sure. The confirmed term drives the Trial search; the free text stays as the Fact's quote.
- On "no" the Respondent is asked again. On "not sure", or when the model can't propose a term with confidence, the Respondent is told to check with their GP, and a Doctor question is raised for the diagnosis.

**Patient search preferences**
- Postcode and maximum travel distance are stored on the patient as search preferences, not as Facts. They are not versioned or cited.
- The postcode is turned into a coarse location point when it is stored. No model ever sees the postcode, the point or the travel limit.
- An optional email or phone number for notices is stored alongside the search preferences. It is never put in a Fact and never sent to a model.

**Return link**
- At the end of the questionnaire the Respondent gets a private return link (an unguessable token for the patient). There are no accounts or passwords.

**Matching module**
- New **Respondent question** type beside Doctor question, with its own storage. A Respondent question is raised when an unknown Criterion result turns on something the Respondent could plausibly know (a date, a medicine name) and their Patient-reported answer is too vague or missing. A Doctor question is raised when the gap needs clinical records or judgement. Each unknown result raises exactly one of the two, never both.
- New public read, `respondent_questions_for_version`, mirroring `questions_for_version` (deduplicated by subject, carrying the Trials each would unblock).
- Code computes the distance from the patient's location point to each of a Trial's sites (site geo points come through Zetaris). The Matcher's input includes "site name, status, km" per site and never the postcode.
- `verdicts_for_version` ranks by Verdict outcome (eligible, then possible with fewest unknowns first, then excluded), then by distance to the nearest recruiting site. Trials beyond the travel limit are returned flagged as further away, not dropped. Distance never changes a Verdict outcome or a Criterion result.

**API** (all thin over the facades above)
- Get the questionnaire definition.
- Submit a questionnaire for a patient: returns the Document hash and run id, and runs ingest and then Re-scan in the background with one correlation id, exactly like an upload. The response includes the return link on first submission.
- Confirm the diagnosis condition term (yes / no / not sure).
- List Respondent questions for a version.
- Set search preferences (postcode, travel limit, optional contact detail).
- Verdict list items gain nearest recruiting site, distance in km and a further-away flag.

**Frontend**
- Web first (Next.js, as planned). The questionnaire is the first screen, with an optional attach-Documents step at the end, then progress, then the ranked Trials. Respondent questions and Doctor questions are shown as separate lists.

## Testing Decisions

- Good tests exercise external behaviour through a module's public surface, using the existing test `Ctx`: fake model, in-memory World Model event store, Postgres reader. Assert on what a caller can observe (outcomes, Facts in a Profile version, Verdicts, questions, model prompts captured by the fake model), never on internal function calls.
- **Seam 1: the record facade.** Submit answers with `submit_questionnaire`, then observe the result through `profile_version` and `diff`. Cover:
  - which Facts appear (including the `Patient` and `AllergyIntolerance` resources), with their quote and page
  - structured answers making no model call
  - free text going through the fake model
  - approximate dates accepted
  - resubmitting identical answers adding no Facts
  - a changed answer adding only the changed Fact in a new version
  - a questionnaire answer contradicting an accepted clinical Fact returning AwaitingPatient with a Conflict
  - the Respondent being recorded on the submission
  - the postcode and contact detail never appearing in any Fact or captured model prompt
- **Seam 2: the matching facade.** Through `verdict`, `verdicts_for_version`, `questions_for_version` and `respondent_questions_for_version`, cover:
  - a vague Patient-reported date near a washout boundary producing an unknown result and a Respondent question, not a Doctor question
  - a missing lab producing a Doctor question
  - the Matcher prompt containing "site name, status, km" and no postcode
  - ranking by outcome then by nearest recruiting site
  - a Trial beyond the travel limit returned and flagged, not dropped
  - the same Verdict outcome with and without location
- HTTP routes and the frontend get no tests of their own in this spec. The routes only call the facades. The pure internals (the loop's `decide()`, the Critic's `review()`) stay table-tested as the scaffold intends, but no new tests are required at that level.
- Prior art: the existing boundary test (each module's facade is its whole public surface), the World Model conformance tests, and the scaffold's design that `decide()` is pure and table-tested.

## Out of Scope

- A WhatsApp or Telegram bot. The questionnaire definition is designed so one can be added later.
- Accounts, passwords and sign-in beyond the private return link.
- Actually sending email or SMS notices. Only the optional contact detail is stored.
- Questions on gender identity, contraception, labs, biomarkers, stage or histology.
- A history of which trial sites existed when a Verdict was made (an open question for the data engineer in the Zetaris trial-storage plan).
- Re-exporting the workflow diagram PNG and restoring source links on the diagram's two new boxes.

## Further Notes

- Vocabulary: GLOSSARY.md now defines Intake questionnaire, Respondent, Patient-reported and Respondent question. "Intake" on its own still means the agent that drafts Facts from a Document.
- Decisions: ADR 0003 (a completed Intake questionnaire is a Document) builds on ADR 0001 (the World Model writes Postgres and agents read through Zetaris) and ADR 0002 (append-only Facts and versioned Verdicts).
- The demo moment this enables: Profile v1 from the questionnaire alone, mostly "possible" with Respondent and Doctor questions; v2 after a genomic report, with the Verdicts that changed and why.
