# Martin

Patient-centric clinical trial matching, built for the Open Agent Hackathon 2026, Track 1: Solving Fragmented Intelligence.

A patient's history is scattered across referral letters, blood reports and genomic results, and trial eligibility lives in free text on ClinicalTrials.gov. TrialMatch (the app in this repo) turns the patient's Documents into dated Facts with Citations, matches them Criterion by Criterion against trials, explains every Verdict, and re-checks when a new Document arrives, because one treatment decision can rule a patient out of a trial.

> **Status: scaffold.** Folders, types, signatures, schema and tests are in place; function bodies raise `NotImplementedError`. Start with [docs/architecture.md](docs/architecture.md).

## How it works

Five agents in two bounded feedback loops:

- **Intake ⇄ Consistency critic:** Document → draft Facts with page citations → rule checks → retry (up to 3) or ask the patient about a Conflict → new Profile version.
- **Matcher ⇄ Evaluator:** each Criterion against the patient's Facts → every claim must cite a Fact → retry (up to 3), then unsupported claims become Doctor questions.
- **Trial fetcher:** ClinicalTrials.gov through Zetaris; only new or changed Trials trigger a Re-scan.

Diagram: [workflow](https://claude.ai/artifact/4kTc9x5oTqnT1vGj1cXANM). Terms: [GLOSSARY.md](GLOSSARY.md). Decisions: [docs/adr](docs/adr).

## Sponsor technology

| Sponsor | How it's used | Where |
|---|---|---|
| **Zetaris** | Data layer. Agents read only through Zetaris SQL; it federates our Postgres and registers ClinicalTrials.gov as a REST table. | `backend/app/sql/reader.py`, `db/zetaris_register.sql` |
| **Meterless World Model** (engine) | Owns the patient timeline: Facts supersede by observation date, Profile versions are snapshots, Verdicts are time-valid relationships, Trial re-fetch is idempotent ingest. Our Python implementation. | `backend/app/worldmodel/` |
| **Meterless Nightshift** | Primary AI provider for every agent. | `backend/app/llm/nightshift.py`, [setup prompt](docs/setup/meterless-provider-prompt.md) |
| **NVIDIA Nemotron** | Models behind Nightshift's lanes (assignment decided later). Every call logs which model answered. | `backend/app/llm/`, `llm_call` table |

**World Model test:** `tests/worldmodel/test_conformance.py` ports the 8 checks from Meterless's conformance runner with the same vectors. Result: not yet passing (engine not implemented).

## Setup (local only)

Zetaris and Meterless must run on your machine (hackathon rule). Hardware: Docker needs 8 GB RAM, 4 CPUs, 15 GB disk.

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
6. Frontend: see [frontend/README.md](frontend/README.md).

## Data and privacy

Real patient documents go in `data/raw/`, which is gitignored and never committed. De-identification runs before any model sees the text. Only de-identified documents go in `data/demo/`.

## Layout

```
backend/app/   record · trials · matching · worldmodel · trace · llm · sql · api
backend/tests/ boundary test, World Model conformance
db/            Postgres schema, Zetaris registration SQL
docs/          architecture, API, ADRs, setup prompts
frontend/      Next.js (to be created)
data/          demo (committed), raw (never committed), trials_snapshot
scripts/       seed, sync, rebuild projections
```
