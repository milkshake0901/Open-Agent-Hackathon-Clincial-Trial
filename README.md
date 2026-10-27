# TrialMatch

Patient-centric clinical trial matching, built for the Open Agent Hackathon 2026, Track 2: The Agent That Can Explain Why.

A patient's history is scattered across referral letters, blood reports and genomic results, and trial eligibility lives in free text on ClinicalTrials.gov. TrialMatch (the app in this repo) investigates those sources together: it reads the patient's Documents and questionnaire into dated Facts with Citations, joins them with trial Criteria read through Zetaris, and answers "can this patient join this trial, and why?" Criterion by Criterion. Every met or not met claim cites the Fact behind it, and the place in the letter it came from, and a second model checks that the Fact supports the claim before the claim is shown. What the evidence can't settle becomes a question for the patient or their doctor. When a new Document arrives the agent re-checks, because one treatment decision can rule a patient out of a trial.

> **Status: working locally, end to end** for the Intake questionnaire: answers → Profile version → Diagnosis check → ranked Verdicts with Citations, Doctor questions and Respondent questions. A few read endpoints (document and version lists, health) and the model fallback for splitting Criteria are still stubs. Developers start with [DEVELOPER.md](DEVELOPER.md), then [docs/architecture.md](docs/architecture.md).

## How it works

Agents in two bounded feedback loops, with a Diagnosis check between them:

- **Intake ⇄ Consistency critic:** Document or questionnaire → draft Facts with page citations → rule checks (code, no model) → retry (up to 3) or ask the patient about a Conflict → new Profile version.
- **Diagnosis check:** the patient's own words for the diagnosis → a shortlist of Condition labels the stored Trials use → the labels they tick become the Condition term, which selects the Open trials to judge ([ADR 0005](docs/adr/0005-condition-term-is-chosen-condition-labels.md)).
- **Matcher ⇄ Evaluator:** each Criterion against the patient's Facts → every met / not met claim must cite a Fact → a second model checks that the Fact supports it → retry (up to 3), then unsupported claims become unknown, and unknowns become Doctor or Respondent questions.
- **Trial ingest:** every ClinicalTrials.gov study with an Australian site, recorded through the World Model; it makes no model call and starts no Re-scan ([ADR 0004](docs/adr/0004-australia-wide-ingest-only-open-trials-judged.md)).

Five model calls in all: the Intake agent, two for the diagnosis shortlist, the Matcher and the Evaluator. Everything else, including the Critic, the Re-scan plan and the Verdict rules, is code.

Diagram: [workflow](https://claude.ai/artifact/4kTc9x5oTqnT1vGj1cXANM). Terms: [GLOSSARY.md](GLOSSARY.md). Decisions: [docs/adr](docs/adr).

## See it without running it

[docs/samples/](docs/samples/README.md) has three real runs from one patient's journey: the MRI letter read into cited Facts, the trial judged on the questionnaire alone (**possible**), and the same trial judged again once the letter arrives (**excluded**, and why). Each shows every model call with the model that answered, and each Criterion with the Fact it cites and the Evaluator's check. [Sponsor technology, in detail](docs/submission/sponsor-tech.md).

## Sponsor technology

| Sponsor | How it's used | Where |
|---|---|---|
| **Zetaris** | Data layer. Agents read only through Zetaris SQL, which federates our Postgres ([ADR 0001](docs/adr/0001-write-postgres-read-through-zetaris.md)); the UI reads Postgres directly. Registering ClinicalTrials.gov as a Zetaris REST table is still a TODO: the ingest calls the API itself. | `backend/app/sql/reader.py`, `db/zetaris_register.sql` |
| **Meterless World Model** (engine) | Owns the patient timeline: Facts supersede by observation date, Profile versions are snapshots, Verdicts are time-valid relationships, Trial re-fetch is idempotent ingest. Our Python implementation, the only writer of the domain tables. | `backend/app/worldmodel/` |
| **Meterless Nightshift** | AI provider for every agent: each calls one gateway, which sends its lane to Nightshift. (A lane can optionally go straight to NVIDIA's API instead; none does by default.) | `backend/app/llm/`, [setup prompt](docs/setup/meterless-provider-prompt.md) |
| **NVIDIA Nemotron** | Nemotron 3 Ultra 550B for every agent: Intake, diagnosis shortlist, Matcher and Evaluator. Lightning 30B was tried as the Evaluator and was about 30x slower per call (it reasons for thousands of tokens), so the Evaluator is a separate prompt on the same model. Every call logs which model answered. | `backend/app/config.py`, `llm_call` table, [DEVELOPER.md](DEVELOPER.md#which-nemotron-serves-each-lane) |

**World Model test:** `tests/worldmodel/test_conformance.py` ports the 8 checks from Meterless's conformance runner with the same vectors. Result: **8/8 passing**.

**Meterless agent engines.** We mount the **World Model** engine: an answer can only explain why if every Fact it cites has a provenance stamp and a date, and if the record shows which Profile version a Verdict was judged against. The World Model gives us both: one grounded record reconciled from scattered Documents, and versions that make "what changed, and why" answerable. We don't mount **H-MEM** or **Markovian**: the patient's state across sessions is already the World Model's Profile versions (a Return link brings the patient back to it), and no task is long enough for chunked reasoning, since each model call is one bounded prompt (the largest is one Trial's Criteria against one Profile version's Facts).

**Evidence.** Every pipeline step and model call, with its full prompt and reply, is written as one JSON line to `data/logs/trialmatch.jsonl`; `backend/scripts/export_run.py <run_id>` turns one run into a readable page (see [docs/samples](docs/samples/README.md)). The World Model's append log and audit are the `wm_event` and `wm_audit` tables, and each run's steps are in `trace_event` and `llm_call`.

## Dependencies

- Python 3.12+ (backend: FastAPI, asyncpg, httpx, pydantic; see `backend/pyproject.toml`)
- Node 20+ (frontend: Next.js 16; see `frontend/package.json`)
- Docker (our Postgres, `docker-compose.yml`)
- **Zetaris**, running locally: the agents' data layer
- **Meterless Nightshift**, running locally: the AI provider for every agent, with its NVIDIA provider set up in Nightshift's Providers tab
- An NVIDIA API key for **Nemotron Parse** (`NVIDIA_PARSE_API_KEY`), only to read uploaded letters

## Setup (local only)

Zetaris and Meterless must run on your machine (hackathon rule), so there is no hosted demo and no offline mode; [docs/samples](docs/samples/README.md) shows real runs instead. Hardware: Docker needs 8 GB RAM, 4 CPUs, 15 GB disk.

1. Install and start Zetaris (Participant Setup Guide, Data section) and Meterless Nightshift (Power section).
2. `cp .env.example .env` and fill in the Zetaris API key and Nightshift runtime token.
3. `docker compose up -d` starts our Postgres with `db/schema.sql`.
4. Run `db/zetaris_register.sql` in the Zetaris SQL Editor, one statement at a time.
5. Backend:
   ```bash
   cd backend
   python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
   .venv/bin/pytest
   .venv/bin/uvicorn app.main:app --reload
   ```
6. Trials: `backend/.venv/bin/python backend/scripts/ingest_trials.py --live` from the repo root (Australia-wide, about 13 pages; until it runs, the app has one saved Trial).
7. Frontend: see [frontend/README.md](frontend/README.md).

## Usage

With the backend on :8000 and the frontend on :3001:

1. Open http://localhost:3001 and answer the Intake questionnaire. Sample input: the answers quoted in [sample 2](docs/samples/2-before-letter-possible.md) (born September 2000, male, "Torn ACL.", diagnosed May 2026, no medicines).
2. Add a letter (PDF). It is de-identified, read by Nemotron Parse into Regions, and drafted into Facts. Review what was read, fix a date if the letter has none, and commit. Sample input: the MRI report in [sample 1](docs/samples/1-letter-read.md).
3. Tick the Condition labels that match the diagnosis. The Re-scan judges each Open trial, and the Trials page shows each Verdict: met and not met Criteria open the letter where the Fact was read, and unknowns become questions for the patient or their doctor.
4. Add another letter and the agent re-checks. [Sample 3](docs/samples/3-after-letter-excluded.md) shows the same trial going from possible to excluded.
5. See how it reasoned: `backend/.venv/bin/python backend/scripts/export_run.py --list`, then `export_run.py <run_id>`.

## Known gaps and next steps

- The Evaluator checks that the cited Fact supports the claim, but not the Matcher's free-text reason ([sample 3](docs/samples/3-after-letter-excluded.md), #14), or that one Fact covers every part of a multi-part exclusion (#8).
- Unknown answers are never checked, so a question routed to the wrong questionnaire item goes unreviewed.
- No offline mode with recorded replies yet (Zetaris and Nightshift must be running).
- ClinicalTrials.gov isn't registered as a Zetaris REST table yet: the ingest calls the API itself.

## Data and privacy

Real patient documents go in `data/raw/`, which is gitignored and never committed. De-identification runs before any model sees the text. Only de-identified documents go in `data/demo/`.

## Layout

```
backend/app/     record · trials · matching · worldmodel · trace · llm · sql · api
backend/tests/   boundary test, World Model conformance
backend/scripts/ ingest_trials, rebuild_projections, meterless, load_referral, extract_document, screen_referral
db/              Postgres schema, Zetaris registration SQL
docs/            architecture, API, ADRs, setup prompts
frontend/        Next.js: questionnaire, Diagnosis check, Trials page
data/            demo (committed), raw (never committed), trials_snapshot
```
