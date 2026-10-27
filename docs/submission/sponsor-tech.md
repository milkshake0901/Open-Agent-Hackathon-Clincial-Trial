# Sponsor technology

TrialMatch answers "can this patient join this trial, and why?" from scattered sources: the patient's letters and
scans, their intake questionnaire, and ClinicalTrials.gov. Each sponsor technology carries one part of that answer.
Figures below come from the operator's log for 26–27 Oct 2026 (`data/logs/trialmatch.jsonl`).

## Zetaris: the agents' data layer

**Role.** Every read an agent makes goes through Zetaris SQL. The agents never touch Postgres directly
([ADR 0001](../adr/0001-write-postgres-read-through-zetaris.md)). The World Model writes its projections (trials,
criteria, sites, Facts, Profile versions, Verdicts) to our Postgres. Zetaris federates that database as the
`trialmatch` datasource, so one SQL query can join a trial's Criteria with the patient's Facts.

**How.**
- [`db/zetaris_register.sql`](../../db/zetaris_register.sql): `CREATE DATASOURCE trialmatch …` over JDBC, then
  `REGISTER DATASOURCE TABLES` for the 18 tables the agents read.
- [`backend/app/sql/reader.py`](../../backend/app/sql/reader.py) `ZetarisReader`:
  `POST {ZETARIS_REST_URL}/sql-editor/sqls/run` with a Bearer key, `X-Org-ID` and a fresh `X-Request-ID` on every
  request. Repo queries are written once against a `SqlReader` protocol. The agents get `ZetarisReader`; the UI and
  tests get `PgReader` running the same SQL text.
- Each query writes a `zetaris.sql` line to the log with its SQL, row count and duration. The log holds **228
  Zetaris queries with 0 errors**. One example, the Matcher loading a Profile version's Facts:
  `SELECT f.id, … FROM trialmatch.profile_version_fact pvf JOIN trialmatch.fact f …` → 10 rows, 401 ms.
- Test: `backend/tests/sql/test_zetaris_live.py` reads trials, sites, criteria, outcomes, Profile versions and
  Verdicts through both readers and checks they match.

**Not done yet.** ClinicalTrials.gov isn't registered as a Zetaris REST table; the ingest calls the API itself and
writes through the World Model. The SQL for it is drafted in `db/zetaris_register.sql`.

## Meterless World Model engine: the patient's timeline

**Which engine.** World Model, implemented in Python in
[`backend/app/worldmodel/`](../../backend/app/worldmodel/): `engine.py`, `resolve.py`, `stable_ids.py`, `store.py`,
and `timeline.py`, which maps TrialMatch onto the engine.

**What it does here.** It is the only writer of the domain tables, so every Fact, Profile version, Trial and
Verdict has provenance and a time range.
- **Facts supersede by observation date.** A newer letter saying something different closes the old Fact rather
  than overwriting it.
- **Profile versions are snapshots.** A Verdict names the version it was judged against, which makes "what changed,
  and why" answerable. In [sample 2 → 3](../samples/README.md) the same trial goes from possible to excluded
  because version 2 adds the MRI letter's Facts.
- **Verdicts are time-valid relationships.** A Re-scan supersedes them; it never edits them.
- **Trial re-fetch is idempotent ingest.** An unchanged ClinicalTrials.gov study records nothing.

**Feature it powers.** The re-check when a new Document arrives, and the citation trail from Verdict → Criterion →
Fact → letter Region.

**Test.** `backend/tests/worldmodel/test_conformance.py` ports the 8 checks from Meterless's conformance runner, with
the same vectors: stable ids, merge bands, provenance required, idempotency, bitemporal supersession, audit order.
**Result: 8/8 passing**
([`docs/samples/worldmodel-conformance.txt`](../samples/worldmodel-conformance.txt)).

**Why not H-MEM or Markovian.** The patient's state across sessions already lives in the World Model's Profile
versions, and no task needs chunked reasoning: each model call is one bounded prompt.

## Meterless Nightshift: the AI provider

[`backend/app/llm/nightshift.py`](../../backend/app/llm/nightshift.py) implements the provider contract (Runtime
1.4, contract v4): OpenAI-compatible base URL (default `http://127.0.0.1:8088/v1`), Bearer runtime token,
`meterless-app` and `meterless-scope: user` headers, `/v1/models` status and Auto Detect.
- Every agent calls one gateway, `app.llm.complete(ctx, lane, …)`. It sends the lane's pinned model to Nightshift,
  parses the reply into a typed schema, and records which model answered.
- A rate-limited (429), 5xx or dropped call is retried with a backoff. Nightshift relays an NVIDIA 429 as a 502, so
  the body is checked too.
- Lanes: `fast` (Intake, diagnosis shortlist), `deep` (Matcher), `judge` (Evaluator).
- The log holds **224 model calls through Nightshift**: 174 fast, 28 deep, 22 judge. 218 were answered by
  `nvidia/nemotron-3-ultra-550b-a55b`. The other 6 failed: five 502s from Nightshift (three of them NVIDIA rate limits relayed) and one dropped
  connection. Those failures are why the 429/5xx/connection retry was added (commit `78d13af`).
  Each `llm.complete` line has `model_requested`, `model_answered`, the prompt, the raw reply, the parsed value and
  `duration_ms`. See any [sample](../samples/README.md).

## NVIDIA

- **Nemotron 3 Ultra 550B** (`nvidia/nemotron-3-ultra-550b-a55b`) through Nightshift serves every agent: Intake,
  diagnosis shortlist, Matcher and Evaluator. The NVIDIA key lives in Nightshift's Providers tab, not in this repo.
- **Why Ultra for the Evaluator too.** We tried Nemotron 3.5 Lightning 30B as the Evaluator. It was about 30x slower
  per call, because it reasons for thousands of tokens before answering. So the Evaluator is a separate prompt on
  Ultra. `DIRECT_LANES` can still put a lane on Lightning ([DEVELOPER.md](../../DEVELOPER.md)).
- **Nemotron Parse** (`nvidia/nemotron-parse`) reads each uploaded letter page into typed Regions (text, section
  header, list item, table) with bounding boxes. Each Fact quotes one Region by id, and the Trials page draws the
  cited Region on the letter. Parse is called on NVIDIA's API directly (`langchain-nvidia-ai-endpoints`), not
  through Nightshift, because Nightshift serves chat models.

## What is unique

1. **A model-checked citation for every claim.** The Matcher must cite one Fact for each met or not met. A second
   prompt, the Evaluator, checks the claim against that Fact read literally. A claim it rejects goes back for a
   retry, and one still unsupported becomes **unknown**, never a guess. The samples include a case the Evaluator
   caught and a case it first missed.
2. **Unknown is a routed question.** An unknown the patient could answer points to the questionnaire item to answer
   again; one that needs records or clinical judgement becomes a question for their doctor.
3. **Explanations that survive change.** Because the World Model versions the record, the agent can say not only
   "excluded because…" but "excluded *since this letter*". Each reason opens the letter at the Region it was read
   from.
4. **Code where code is enough.** Of the pipeline, only five model calls are model calls: Intake, two for the
   diagnosis shortlist, Matcher and Evaluator. The Critic, Re-scan plan and Verdict rules are deterministic code,
   so the reasoning a judge sees is the reasoning that happened.
