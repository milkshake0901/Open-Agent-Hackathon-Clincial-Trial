# Public HTTP API (consumed by the Next.js frontend)

Base: `http://localhost:8000/api`. JSON unless noted. Wire schemas live in `app/api/schemas.py` and are built from domain types; the frontend generates TS types from `/openapi.json`. Long work returns `202` with a `run_id`; the UI follows the run.

| Method | Path | Request | Response | Facade call |
|---|---|---|---|---|
| POST | `/patients` | `{label}` | `201 {patient_id}` | insert |
| POST | `/patients/{pid}/documents` | multipart `file` (one PDF per request; several at once are several requests) | `202 {document_hash, run_id, deduplicated: bool}`; a re-upload of the same bytes answers with the earlier run unless it was rejected; `422` unreadable (not a PDF, no text layer), `413` over 20 MB | `record.register_document` then bg `record.ingest` → `matching.rescan` on Committed (same run_id) |
| GET | `/patients/{pid}/documents` | | `[{hash, filename, page_count, uploaded_at, version_number?}]` | `record.*` |
| GET | `/patients/{pid}/documents/{hash}/pages/{n}` | | `{number, text, tables}` (de-identified) | citation viewer |
| GET | `/patients/{pid}/versions` | | `[{id, number, document_hash, fact_count, created_at}]` | `record.versions` |
| GET | `/patients/{pid}/versions/{vid}` | | `{id, number, facts: [{id, resource, subject, value, unit, observed_on, citation:{document_hash,page,quote}}], current: {subject: fact_id}}` | `record.profile_version` |
| GET | `/patients/{pid}/versions/{vid}/diff?from={vid0}` | | `{facts_added: [...], subjects_changed: [{subject, before?, after}], verdicts_changed: [VerdictChange]}` | `record.diff` + `matching.change_between` per trial |
| GET | `/runs/{run_id}` | | `{run_id, kind, head, state: IngestRunState \| null, events: [{seq, at, kind, actor, causation_id, payload}]}`; an ingest's `state.phase` is `started\|drafting\|awaiting_patient\|committed\|rejected`, with `version_number` and `reason` | `trace.read` + `reduce_ingest` |
| GET | `/runs/{run_id}/events?since={seq}` | | `{head, events: [{seq, at, kind, actor, summary, payload}]}` (poll every ~1 s; SSE optional) | `runs.read(since_seq)` |
| GET | `/runs/{run_id}/conflicts` | | `{run_id, conflicts: [{id, message, draft, accepted}]}`; each side `{document_hash, filename, page, page_text, quote, value, unit, observed_on, label}`; empty once the run moved on | `record.conflicts` |
| POST | `/runs/{run_id}/confirm` | `{resolutions: [{conflict_id, choice: keep_accepted\|accept_draft\|discard_both}]}` | `202` same body as a questionnaire submission (`outcome`, `version_number`, `rescan`); Re-scan runs inline on committed; `422` unknown Conflict | `record.confirm` |
| POST | `/trials/sync` | `{condition, location, max_trials?}` | `200 SyncReport {fetched, new[], changed[], unchanged[], source}`; if `changed` and a current version exists → `202 {run_id}` for the narrowed rescan | `trials.sync` → `matching.rescan(only=changed)` |
| GET | `/trials` | | `[{nct_id, title, status, criterion_count, eligibility_hash, fetched_at, source}]` | `trials.active_trials` |
| GET | `/trials/{nct}` | | `{..., criteria: [{id, kind, ordinal, text}]}` | `trials.trial` + `trials.criteria` |
| POST | `/patients/{pid}/versions/{vid}/rescan` | | `202 {run_id}` (manual; idempotent — a no-op rescan finishes immediately with `rescan.planned` showing all skipped) | `matching.rescan` |
| GET | `/patients/{pid}/versions/{vid}/verdicts` | | `{profile_version_id, verdicts: [Verdict]}` ranked by outcome (possible: fewest unknowns first), then nearest recruiting site; each Verdict also has `nearest_site: {name, status, km} \| null` (nearest recruiting site), `sites: [{name, status, km}]` (3 nearest open sites) and `further_away: bool` (no recruiting site within the travel limit; listed, never dropped). `km` is null when the distance is unknown. The postcode is never returned | `matching.verdicts_for_version` |
| GET | `/patients/{pid}/versions/{vid}/verdicts/{nct}` | | `{nct_id, outcome, eligibility_hash, stale: bool, attempts, unsupported_downgraded, run_id, results: [{criterion:{id,kind,text}, outcome, rationale, citation?: {fact_id, document_hash, page, quote}}], questions: [{criterion_id, subject, text}]}` | `matching.verdict` |
| GET | `/patients/{pid}/versions/{vid}/verdicts/{nct}/change?from={vid0}` | | `VerdictChange {outcome_from, outcome_to, criteria_changed: [{criterion_id, text, outcome_from, outcome_to, citation?}]}` | `matching.change_between` |
| GET | `/patients/{pid}/questions?version={vid}` | | `[{subject, text, criterion_ids[], nct_ids[]}]` deduped by subject | `matching.questions_for_version` |
| GET | `/traces/{correlation_id}` | | causal tree of every event across an ingest and its Re-scan, with `llm_call` rows (requested vs answered model) | `trace.causal_tree` |
| GET | `/health` | | `{postgres, zetaris, nightshift: {ok, lanes: {fast, deep, judge}}, world_model}` | startup checks |
| GET | `/return/{token}` | | `{patient_id, profile_version_id?, version_number?}`; unknown token → bare `404`. The token comes once, as `return_token` on the first `POST /patients/{pid}/questionnaire` response | `record.patient_for_return_token` + `record.current_version` |

Errors: `404` unknown ids; `409` when `/confirm` is called on a run not in `awaiting_patient`; `422` validation; `503 {reason}` when Nightshift is unavailable (runs then end `run.rejected` / `rescan.finished` with `failed`).

Frontend pages → endpoints: Upload+timeline (`documents`, `versions`, `runs/{id}/events`), Ranked trials (`verdicts`, `verdicts/{nct}`, `change`), Trace page (`runs/{id}`), Doctor questions (`questions`), Conflict dialog (`runs/{id}/conflicts` + `confirm`).
