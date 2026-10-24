# Meterless engine additions: handoff

Handoff from a planning session (24 Oct 2026). Paste this file into a new Claude session, or tell it to read `docs/plans/meterless-engine-additions.md`, to continue from here.

## Prompt to start a new session

```
Read docs/plans/meterless-engine-additions.md, then README.md, DEVELOPER.md,
docs/architecture.md and docs/adr/. My .env is already filled in locally
(Zetaris and Nightshift); never print its values. Continue from "Next steps".
Don't change an existing ADR or add a new one without showing me the edit first.
```

## Situation

- **Event:** Open Agent Hackathon 2026 (GenAI.Works, with Zetaris, NVIDIA and Meterless as sponsors). Our deadline: 27 Oct 2026, so about 4 days left as of 24 Oct.
- **Team:** 2 people.
- **Repo state:** a scaffold. 38 backend files raise `NotImplementedError`; only `config`, `ctx`, `main` and `api/schemas` are filled in. `frontend/` hasn't been created.
- **Local setup:** the user has filled in `.env` on their own machine. It hasn't been confirmed whether Zetaris, Nightshift and the Nemotron lane actually respond; run the checks in Next steps.
- **Unknown:** which machine runs Nightshift, and whether it can run jobs overnight.

## Rules from the participant guide (PDF, last updated 21 Oct 2026)

- **Eligibility:** Zetaris and Meterless must both run on the user's own machine.
- **Data:** the project must use Zetaris. Zetaris can't read files on the laptop. Agents send SQL over REST: `POST {ZETARIS_REST_URL}/sql-editor/sqls/run` with a Bearer key, `X-Org-ID: 1` and a fresh `X-Request-ID` UUID on every request.
- **Build:** at least one Meterless engine (H-MEM, Markovian, World Model or Scout Intent) must power a working feature, backed by a passing conformance suite, eval or feature test. Only mentioning an engine doesn't count, and neither does the "Add Meterless as a provider" prompt on its own.
- **Power:** Meterless Nightshift must be the app's primary AI provider. It's OpenAI-compatible (`METERLESS_BASE_URL`, default `http://127.0.0.1:8088/v1`) and every request needs:
  - `Authorization: Bearer <runtime token>`
  - a `meterless-app` header
  - `meterless-scope: user`
  - Endpoints: `GET /v1/models` and `POST /v1/chat/completions`.
  - The NVIDIA key goes only in Nightshift's Providers tab, never in our `.env`.
- **NVIDIA Nemotron award (a DGX Spark):** a Nemotron lane must materially power a feature. Pin it to a Nemotron-backed lane, because `meterless/auto` may route to another model. Suggested lanes are `nvidia/nemotron-3.5-lightning-30b-a3b` (fast) and `nvidia/nemotron-3.5-super-vl-120b-a12b` (deep). Judged on technical depth, usefulness and polish.
- **What to show judges:** the app solving a useful problem, its Meterless provider connection, and one real request going through Nightshift and coming back. Hide all keys.
- **Zetaris tracks:** *Solving Fragmented Intelligence* (our README's Track 1) and *The Agent That Can Explain Why*. TrialMatch fits both.

## Judging rubric we're scoring against

The guide gives no rubric for these tracks, so we use the Meterless one from `docs/community/hackathon-guide.md` in Meterless/Meterless: Usefulness 30%, Meterless engine usage 25%, Local-first and privacy 15%, Quality of demo 15%, Creativity 10%, Documentation 5%.

**Privacy caveat:** a Nemotron lane served by NVIDIA's hosted endpoint sends text to the cloud. De-identification has to run before any model call, which `record.register_document` already requires, and the demo shouldn't claim the system is "fully local".

## Five proposed additions

All five are on top of the core build; they don't replace any of it. None of them contradicts ADR 0001 or ADR 0002.

| # | Addition | Effort (h) | Payoff | Engines | Files touched |
|---|---|---|---|---|---|
| 1 | **"Why did it change?" time travel.** Walk the World Model from a Verdict to its criterion results, then to the Fact that superseded the old one, then to the Document page. Add a slider showing what the system believed at v3 and at v4. | 6–8, once the World Model passes | **H**: Usefulness, Engine usage, Demo, Explain Why track | World Model | `worldmodel/timeline.py`, `matching/__init__.py` (`change_between`), `matching/types.py`, `api/verdicts.py`, frontend Why page |
| 2 | **Scout Intent guard before every model call.** Check each page for prompt injection and for patient details de-identification missed. A page that fails goes only to a local lane, never to the cloud Nemotron lane. Each signed contract is logged to the trace. | 10–14 | **H**: Local-first and privacy, Engine usage (runnable eval harness: `SCOUT_IMPL=<path> npm run evals`), NVIDIA award | Scout Intent | new `app/guard/` module, `record/__init__.py`, `llm/__init__.py`, `trace/events.py`, `tests/test_boundaries.py`, `GLOSSARY.md` |
| 3 | **Markovian Intake for long Documents.** Read a 20–30 page referral pack in bounded chunks, carrying a compressed state forward between chunks. Shows token cost staying flat. | 8–10 | **M**: Engine usage; lets small local models handle long packs | Markovian | `record/intake.py`, `record/loop.py`, `trace/events.py` |
| 4 | **H-MEM memory of matching lessons.** When the Evaluator rejects a claim, record the lesson against the criterion's wording, and have the Matcher retrieve it on later Re-scans. Holds no patient data. | 12–16 | **M**: Engine usage, Creativity | H-MEM | new `app/lessons/` module, `matching/matcher.py`, `matching/evaluator.py`, `db/schema.sql` |
| 5 | **Overnight trial watch.** A nightly Nightshift job syncs ClinicalTrials.gov; World Model `ingest` reports which trials changed, and only those are re-checked. Morning view: "2 trials changed, 1 new possible match". | 8–12, if the hardware allows | **M**: Usefulness, Track 4 story | World Model, Nightshift | `trials/__init__.py`, `scripts/sync_trials.py`, `matching/loop.py`, `api/trials.py` |

**ADRs:** #2 and #4 would each need a *new* ADR 0003, not a change to an existing one:

- #2: "pages that fail the guard never reach a cloud lane."
- #4: "H-MEM holds lessons about matching, never patient Facts."

Neither has been drafted. The user approves every ADR change before it's made.

## Recommendation: start with #1

- **It's almost free.** The World Model has to pass 8/8 anyway, because that's the Build-rule evidence, and `change_between` is already designed.
- **It makes the engine-usage score obvious.** Judges see supersession, versioned edges and as-of queries working on screen.
- **It is the Explain Why track.**
- **It keeps risk low.** It adds no new module, ADR or dependency.

#2 is the next best addition if time allows.

### Architecture sketch

```
UI "Why did it change?"  ──GET /api/verdicts/{nct}/change?from=v3&to=v4──▶ api/verdicts.py
                                                                             │
                                                matching.change_between(ctx, nct, v3, v4)
                                                                             │
                ┌────────────────────────────────────────────────────────────┤
                ▼                                                            ▼
   Verdict at v3 / v4                                         criterion_result rows (via Zetaris)
   wm.edges_from(patient, via="verdict", at=t)                each cites fact_id
   (old edge closed, new edge open)                                          │
                                                                             ▼
                                              wm.about(patient, include_superseded=True)
                                              → Fact v3 "EGFR: unknown"  superseded by
                                                Fact v4 "EGFR exon 19 del" (observed 2026-09-30)
                                                                             │
                                                                             ▼
                                              Provenance → Document hash + page → page image
```

`VerdictChange` gains a `because` chain: Verdict, then criterion, then the Fact before and the Fact after, then the Citation. The slider calls the same endpoint with `at=<version time>`. Every link still works because nothing is ever deleted (ADR 0002). The engine signatures this relies on already exist in `worldmodel/engine.py`: `entity_at`, `edges_from(..., at=)` and `about(..., include_superseded=True)`.

### Two-minute demo script

| Time | On screen | Say |
|---|---|---|
| 0:00–0:15 | Patient "M." with 3 de-identified Documents, 10 lung cancer (NSCLC) trials in Sydney | "Her history is in three PDFs, and trial eligibility is free text. Nobody has time to cross-check them." |
| 0:15–0:40 | Upload the referral letter and blood report. Verdicts appear. Click one Citation, and page 2 of the blood report opens. | "Every claim cites a page. If the Evaluator can't find a supporting Fact, it asks the doctor a question instead of guessing." |
| 0:40–0:55 | Upload an *older* blood report. The profile stays the same. | "It's older, so it doesn't override anything. The World Model orders Facts by when they were observed, not when they were uploaded." |
| 0:55–1:20 | Upload the genomic report. Profile v4 is created, and only affected Trials are re-checked. NCT-X flips from *excluded* to *possible*. | "One new document, one changed answer." |
| 1:20–1:45 | Open "Why did it change?" The chain shows: Verdict → criterion "EGFR-positive" → unknown at v3 → met at v4 → genomic report page 2. Drag the slider back to v3. | "This is what we believed last Tuesday, and why. The old reasoning is still there, with its citations intact." |
| 1:45–2:00 | Trace panel: the Nemotron lane through Nightshift, the Zetaris query, the retry count. Then the terminal shows `test_conformance.py` 8/8. | "Local data layer, local runtime, an engine that passes its conformance tests, and an answer you can audit." |

## Next steps

1. **Check the local stack** (the user's machine; never print `.env` values):
   - In the `zetaris-platform` folder, run `./verify.sh` and confirm 9/9 checks pass.
   - Run the guide's `smoke_test.py` and confirm three PASS lines.
   - Send `GET /v1/models` to Nightshift and confirm a Nemotron model is listed and assigned to a lane.
2. Implement `backend/app/worldmodel/` until `backend/tests/worldmodel/test_conformance.py` passes 8/8. This is the Build-rule evidence and what #1 depends on.
3. Implement `llm/nightshift.py` from `docs/setup/meterless-provider-prompt.md`, with the headers listed above and a lane pinned to Nemotron.
4. Write the core flow: Intake ⇄ Critic → commit → Re-scan → Matcher ⇄ Evaluator, plus `db/zetaris_register.sql`.
5. Build #1, "Why did it change?", then the frontend Why page.
6. If time allows, build #2: draft ADR 0003 first and get the user's approval.

## Open questions

- Which machine runs Nightshift, and can it run overnight? This decides #5.
- Does Lightning SQL accept our queries, and does Zetaris cache reads? See the open risks in `docs/architecture.md`.
