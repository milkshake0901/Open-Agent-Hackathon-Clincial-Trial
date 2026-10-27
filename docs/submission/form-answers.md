# HackOS submission form: draft answers

Paste into the form; check every field before you submit.

**Project name:** TrialMatch

**Track:** 2 · The Agent That Can Explain Why

**One-line description:** An agent that reads a patient's letters and questionnaire, checks them against every
open clinical trial in Australia, and explains each answer Criterion by Criterion, with every claim cited to the
letter it came from and checked by a second model.

**Description (short paragraph):** A patient's history is scattered across referral letters, scans and blood
reports, and trial eligibility lives in free text on ClinicalTrials.gov. TrialMatch investigates both. Nemotron
Parse reads each letter into Regions, and an Intake agent drafts dated Facts that each quote one Region. The
Meterless World Model reconciles them into one versioned patient record. The Matcher then judges every trial
Criterion against those Facts, read through Zetaris. Each met or not met must cite a Fact, an Evaluator checks that
the Fact supports it, and whatever the evidence can't settle becomes a question for the patient or their doctor.
When a new letter arrives, the agent re-checks and shows what changed and why. Every model call runs on Nemotron 3
Ultra through Meterless Nightshift and is logged with the model that answered.

**Team members:** _confirm the roster before creating the submission (team lock)._

**Repository:** https://github.com/milkshake0901/Open-Agent-Hackathon-Clincial-Trial (must be public)

**Colab links:** none; the agents run locally.

## Pre-existing components

All product code was written during the build window. The first commit is 23 Oct 2026 07:25 UTC, after the window
opened on 22 Oct 00:00 UTC.

Declare:
1. **Open-source libraries** (unchanged): FastAPI, Uvicorn, asyncpg, httpx, Pydantic, LangChain
   (`langchain-openai`, `langchain-nvidia-ai-endpoints`), Next.js, React, Tailwind CSS, and their dependencies.
2. **Meterless World Model conformance vectors.** `backend/tests/worldmodel/test_conformance.py` ports the 8 checks
   and test vectors from Meterless's `engines/world-model/conformance/runner.ts`. The engine implementation is ours.
3. **Meterless provider contract.** `docs/setup/meterless-provider-prompt.md` is the "Add Meterless as a provider"
   prompt from the Meterless setup guide; `backend/app/llm/nightshift.py` implements it.
4. **ClinicalTrials.gov data.** Public study records, fetched by our ingest during the window.
5. **Patient documents** used for testing (the ACL MRI report and others): real documents that existed before the
   window. They are de-identified before any model sees them, and they are not in the repository.
