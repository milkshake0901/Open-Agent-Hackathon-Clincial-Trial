# The World Model writes Postgres; agents read through Zetaris

Status: accepted, amended 2026-10-23 (originally "the app writes Postgres directly").

Zetaris is the required data layer, but it federates over other stores rather than owning writes, it exposes Postgres read-only, and it cannot read files on the laptop. So our own Postgres container holds the data, Zetaris registers that Postgres and the ClinicalTrials.gov API as sources, and every agent reads only through Zetaris SQL. Source PDFs never enter Zetaris; only Facts extracted from them do, each carrying its Document hash and page.

**Amendment.** The Meterless World Model engine is the only writer of the domain tables (fact, profile_version, trial, criterion, verdict, criterion_result, doctor_question). Each World Model event is appended to `wm_event` and projected into those tables in the same transaction, so the engine's log and what Zetaris reads cannot disagree. We chose this over keeping the World Model as a side store for run state because the engine's primitives (facts that supersede by observation time, bitemporal relationships, snapshots, idempotent ingest) are exactly the patient timeline, and a side store would be decoration.

## Consequences

- Owners: `wm_event`/`wm_audit` and the projected domain tables belong to `app.worldmodel`; `patient`/`document`/`document_page` to `app.record.repo`; `trace_*`/`llm_call` to `app.trace`.
- There are two read paths to the same data (Postgres for the UI, Zetaris for agents). An agent that reads right after a write uses a bounded visibility wait because Zetaris may cache.
- Our Postgres is separate from the `postgres` container inside the Zetaris bundle, which is Zetaris's internal store.
- `backend/scripts/rebuild_projections.py` must be able to rebuild every projected table from `wm_event` alone.
