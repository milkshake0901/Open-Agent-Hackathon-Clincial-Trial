# Sample runs

Three real runs from one patient's journey, exported from the operator's log (`data/logs/trialmatch.jsonl`) with
`backend/scripts/export_run.py`. Each page shows every model call (lane, the model that answered, prompt and reply)
and, for a Re-scan, each Criterion with its decision, the Fact it cites and the Evaluator's check.

The patient: a 26-year-old with a torn ACL, matched against **NCT06956339** (Cross Bracing Protocol Versus Surgery
for Acute ACL Rupture, recruiting in Melbourne). Every model call was answered by `nvidia/nemotron-3-ultra-550b-a55b`
through Meterless Nightshift.

| # | Input | Output | What it shows |
|---|---|---|---|
| 1 | [MRI letter, read into Regions](1-letter-read.md) | 13 draft Facts, each quoting one Region | **Intake ⇄ Critic.** The letter carries no date, so the Critic (code, no model) sends all 13 drafts back for a missing observed-on date; after 3 attempts the bound stops the loop and the letter goes to review, where the date is entered. |
| 2 | [Questionnaire only (Profile v1, 10 Facts)](2-before-letter-possible.md) | **possible**: 1 met, 1 not met, 14 unknown | **Matcher ⇄ Evaluator, warts included.** The Matcher twice labels the pregnancy exclusion *met* (the patient is pregnant) from a Fact that says "No". The Evaluator passes it the first time, with a reason that contradicts the label, then rejects it; the third attempt says not met. 10 questions are raised (5 for the patient). |
| 3 | [Questionnaire + MRI letter (Profile v2, 23 Facts)](3-after-letter-excluded.md) | **excluded** | **Why it changed.** The letter's "high grade partial tear, near full thickness … some contiguous fibres" makes inclusion #2 (a *complete* tear) not met. The Evaluator rejects one claim (#10, cited a Fact about chondral wear for a dislocation exclusion); the Matcher fixes it to unknown on retry. |

[`worldmodel-conformance.txt`](worldmodel-conformance.txt): the Meterless World Model conformance suite, 8/8 passing.

## Privacy

The letter is de-identified before any model sees it (`[PATIENT]`, `[DOB]`, `[CLINICIAN-1]`). In these exports
the referring clinic's name and address are also replaced with `[CLINIC NAME AND ADDRESS REDACTED]`. Birth month is
the finest date of birth the app stores.

## Make your own

```bash
backend/.venv/bin/python backend/scripts/export_run.py --list            # runs in the log, newest last
backend/.venv/bin/python backend/scripts/export_run.py <run_id>          # writes docs/samples/<run_id>.md
```
