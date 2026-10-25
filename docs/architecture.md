# Architecture

TrialMatch turns a patient's scattered clinical Documents into dated, cited Facts, matches them against ClinicalTrials.gov eligibility Criteria, explains every Verdict with Citations, and re-checks whenever the record changes. Vocabulary: [GLOSSARY.md](../GLOSSARY.md). Decisions: [docs/adr](adr). HTTP endpoints: [api.md](api.md).

Status: scaffold. Types, signatures and pseudocode are in place; bodies raise `NotImplementedError`. The sketch is the contract: if implementation needs something it doesn't anticipate, raise it rather than working around it.

## How a caller uses it

```python
from app import record, trials, matching, trace

outcome = await record.ingest(ctx, document_hash)          # Intake ⇄ Critic loop, bounded
match outcome:
    case record.Committed(version=v):    await matching.rescan(ctx, v.id)   # idempotent
    case record.AwaitingPatient(conflicts=cs): ...          # UI asks the patient; record.confirm(...)
    case record.Rejected(reason=r): ...

await trials.ingest(ctx, trials.LivePages())   # every Australian study (ADR 0004); no model call, no Re-scan
change = await matching.change_between(ctx, "NCT0123", v3, v4)   # why did the Verdict move?
log = await trace.read(ctx.ui_reader, run_id)                     # how the system reasoned
```

## Shape

```
backend/app/
  record/      Documents, Facts, Profile versions, Conflicts; Intake ⇄ Critic loop
  trials/      Trials, eligibility hashing, Criteria (ClinicalTrials.gov through Zetaris)
  matching/    Criterion results, Verdicts, Doctor questions; Matcher ⇄ Evaluator loop; Re-scan
  worldmodel/  Meterless World Model engine (our Python implementation) + timeline adapter + projector
  trace/       run events with causal envelope, model-call log
  llm/         Nightshift client and lanes; FakeLLM for tests
  sql/         one writer, two readers (Postgres for UI, Zetaris for agents)
  api/         thin HTTP routes
```

**Modules own knowledge, not execution order.** Each module's `__init__.py` is its whole public surface; `tests/test_boundaries.py` fails the build on cross-module internal imports. The agents are files inside the module that owns the decision they inform (intake and critic in `record`, matcher and evaluator in `matching`).

**Loops are bounded state machines.** `record/loop.py` and `matching/loop.py` each have a pure `decide()` returning a closed set of steps (Retry, Escalate/Approve, Accept, Exhausted). The bound is a setting; exhaustion is a transition, not an exception. Conflicts never retry: re-reading a Document cannot change what it says, so they go to the patient. When the Matcher ⇄ Evaluator loop exhausts, unsupported claims become `unknown` (and so Doctor questions) and the Verdict is flagged `degraded`; an uncited "met" can never be stored.

**Citations are enforced three times.** In types (`ValidatedResults` is produced only by the evaluator, and a `Verdict` needs one), in the evaluator (a deterministic structure check runs before any model is asked whether the Fact supports the claim), and in the database (`CHECK ((outcome = 'unknown') = (fact_id IS NULL))`).

**The World Model owns the patient timeline** ([ADR 0001](adr/0001-write-postgres-read-through-zetaris.md)). `worldmodel/timeline.py` is the only code that maps domain operations to engine primitives: Fact → `assert_fact` (observed-on date is the record time, so supersession gives "current"), Profile version → `snapshot`, Trial → `ingest` keyed by NCT ID (its `changed` flag narrows the Re-scan), Verdict → `relate` patient→trial (old edges close, so "what did we believe at v3" is a point-in-time query). Every engine event is projected into the relational tables in the same transaction; Zetaris reads those.

**Re-scan is a set difference.** Judge every active Trial lacking a Verdict for (NCT, current eligibility hash, Profile version). Running it twice does nothing the second time. Each Verdict commits on its own, so a crash loses at most the Trials in flight.

**The trace is the record of what happened.** Every loop step is an event in `trace_event` with actor, causation id (so the UI draws a tree), correlation id (one upload threads through its ingest and Re-scan), and links to `llm_call` rows showing which model was requested and which answered. Event ids are deterministic, so a duplicate append after a crash is ignored.

## Synthesis decision

Two candidate designs were sketched in parallel and scored by a separate judge.

- **Base: domain modules with explicit bounded loops.** Buildable by two people in four days, short call chains (any flow traces in three files), and a different engine API touches one adapter file.
- **Rejected: event-centric** (agents as reactors on the World Model event log). Strongest on single ownership and idempotence, but it needs a reactor runtime (cursors, dedupe, re-gather) before any product exists, and it assumed an engine API (versioned streams, optimistic append) that the real engine doesn't have.
- **Grafted from the event-centric design:** the causal trace envelope and `llm_call` table; deterministic event ids; the `degraded` flag; the deterministic citation check before the judge-lane check; same-transaction projection of engine events.
- **Changed after reading the real engine** (Meterless/Meterless `engines/world-model`): both candidates assumed an event-stream API. The real engine is a provenance-tracked world graph, which fits the patient timeline better than either candidate's use of it, so it now owns Facts, Profile versions, Trials and Verdicts instead of only run state. Its TypeScript conformance runner cannot load Python, so its 8 checks are ported with the same vectors in `tests/worldmodel/test_conformance.py`.

## Tradeoffs accepted

- `record.ingest` is one long call (PDF → de-identification → up to 3 model round-trips → commit) so callers never coordinate stages; progress is visible through the trace.
- The Verdict outcome is derived from criterion results by a pure function, not proposed by the model.
- Two read paths (Postgres, Zetaris) share one set of ANSI SQL queries; Lightning SQL quirks surface in one file per module.
- No queue or worker process: runs are in-process background tasks; idempotence makes a restart safe.
- A Re-scan re-judges every Trial against a new Profile version (no reuse of unchanged criterion results), keeping Verdicts simple to explain. The demo set should be about 10 Trials.

## Open questions and risks

- Does Lightning SQL accept our query style (array parameters, window functions), or must `ZetarisReader` rewrite them? One-hour spike on day 1.
- Does Zetaris cache our Postgres reads, and how long? Decides the visibility-wait bound.
- How many parallel requests does local Nightshift serve? Bounds Re-scan time in the demo.
- Which Nightshift model serves each lane: decided later (`Settings.lane_models`).
- What the UI shows when a model call fails mid-run (currently: the run ends failed with the reason).

## Next implementation step

Implement `app/worldmodel` until `tests/worldmodel/test_conformance.py` passes 8/8, then `record/critic.py` and both `decide()` functions as pure, table-tested code.
