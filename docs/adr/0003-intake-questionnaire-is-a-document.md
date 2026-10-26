# A completed Intake questionnaire is a Document

Status: accepted, 2026-10-24. Since ADR 0006 a letter is no longer copied into the questionnaire: Intake reads the letter itself, and the questionnaire asks only what the letter didn't answer.

Respondents answer an Intake questionnaire before (or instead of) uploading clinical documents, and those answers must be citable, versioned and comparable with what later Documents say. So a completed questionnaire is stored as a Document (rendered to text, hashed, one page per section), and its answers become ordinary Patient-reported Facts through the same Critic and commit path. Structured answers (birth month, sex, yes/no) map to Facts in code; free-text answers (diagnosis, treatments, approximate dates) go through the Intake agent, which stores a best-estimate observed-on date and keeps the verbatim quote. Correcting an answer is a new full submission: a new Document and Profile version, with unchanged answers dropped as duplicates. Birth month and sex use a new `Patient` Fact resource, allergies a new `AllergyIntolerance` one. Postcode and travel distance are search preferences on the patient, not Facts: no model ever sees the postcode; code computes the distance to each site and models see only "site name, status, km". Distance ranks Trials but never changes a Verdict.

This means a questionnaire answer contradicting a referral letter raises a Conflict, a Verdict can cite "intake questionnaire, Q4", and "v1 from the questionnaire, v2 after the genomic report" falls out of ADR 0002 unchanged.

## Considered options

- A separate answers table: no Conflicts with clinical Facts, the Matcher reads two sources, a met Criterion on age or sex cannot be cited (`fact_id` is required), and edits either overwrite (breaking ADR 0002) or need their own versioning.
- Answers as attributes on the patient row: same problems, plus no history at all.
- Every answer through the Intake agent: wasteful and error-prone for answers that are already structured.
