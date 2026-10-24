# Facts are append-only; a Verdict belongs to a Trial's criteria and a Profile version

Status: accepted, amended 2026-10-23 (Verdict key now includes the eligibility hash) and 2026-10-24 (a later questionnaire submission supersedes an earlier one).

A Document can arrive out of order (an old blood report uploaded after a newer one), and the product's value is showing how eligibility changes as the record grows. So Facts are never updated or deleted, "current" is derived from the latest observed-on date rather than the latest upload, each accepted Document creates a new Profile version, and every Verdict is keyed by (Trial, eligibility hash, Profile version). This lets us show "excluded under v3, possible under v4 because the genomic report arrived" and keeps every Citation valid forever.

**Amendment.** The key gained the eligibility hash. When a Trial edits its eligibility text while the patient's record is unchanged, the old Verdict (judged against the old Criteria) is kept beside the new one instead of being overwritten.

**Amendment (2026-10-24).** Among Patient-reported Facts for the same subject, a later Intake questionnaire submission supersedes an earlier one whatever their observed-on dates: a resubmission is a correction. Otherwise a clarified answer ("2 March 2025") would lose to the stored best estimate of a vaguer one ("around March 2025", estimated as 15 March). Clinical Facts still go by the latest observed-on date, and a clinical Fact against the (latest) Patient-reported Fact still does too.

In the World Model these map directly: a Fact is `assert_fact` with the observed-on date as its time (later observations supersede), a Profile version is a `snapshot`, and a Verdict is a `relate` edge from patient to Trial whose earlier edges close rather than disappear.

## Considered options

- Overwrite the patient's current values in place: simpler queries, but loses the before/after story and breaks old Citations.
- Key Verdicts by Trial only: smaller table, but a Re-scan silently destroys the explanation of why a Verdict changed.
- Key Verdicts by (Trial, Profile version): loses the old Verdict when a Trial's criteria change.
