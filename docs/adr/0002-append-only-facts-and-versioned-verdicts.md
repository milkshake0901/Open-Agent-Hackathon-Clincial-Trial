# Facts are append-only; Verdicts belong to a Profile version

A Document can arrive out of order (an old blood report uploaded after a newer one), and the product's value is showing how eligibility changes as the record grows. So Facts are never updated or deleted, "current" is derived from the latest observed-on date rather than the latest upload, each accepted Document creates a new Profile version, and every Verdict is keyed by (Trial, Profile version) rather than by Trial alone. This lets us show "excluded under v3, possible under v4 because the genomic report arrived" and keeps every Citation valid forever.

## Considered options

- Overwrite the patient's current values in place: simpler queries, but loses the before/after story and breaks old Citations.
- Key Verdicts by Trial only: smaller table, but a Re-scan silently destroys the explanation of why a Verdict changed.
