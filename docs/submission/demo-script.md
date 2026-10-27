# Demo video: script and shot list

Target **3:30** (hard limit 4:00). Record from a real run, using the ACL patient from [docs/samples](../samples/README.md).

**Before recording**
- Start Postgres, Zetaris, Nightshift, the backend (:8000) and the frontend (:3001). Run one Re-scan first to check
  Zetaris answers. The Zetaris → Postgres connection dropped intermittently on 27 Oct (`test_zetaris_live.py`
  failed twice, each time on a different test). If it drops mid-take, record the Re-scan again.
- Close `.env`, the terminal history and any tab showing a token. In the Nightshift console, hide the runtime token
  and the Providers tab key.
- Use only the de-identified ACL letter. Never show the `Prostate Cancer/` documents.
- Browser zoom 125%, one window, notifications off.

| Time | Screen | Say (roughly) |
|---|---|---|
| 0:00–0:20 | Title card, then ClinicalTrials.gov showing one trial's long eligibility text | "A patient's history is spread across letters and scans. Trial eligibility is pages of free text. Patients and their doctors can't check hundreds of trials by hand, and a yes or no with no reason is useless. TrialMatch answers *can I join this trial, and why*." |
| 0:20–0:50 | Questionnaire: born Sept 2000, male, "Torn ACL", May 2026, no medicines. Submit → Profile v1 with each Fact's source | "The patient starts with a short questionnaire. Every answer becomes a dated Fact that says where it came from." |
| 0:50–1:00 | Diagnosis check: tick the ACL condition labels | "They confirm which condition labels match, and that picks the open trials to judge." |
| 1:00–1:20 | Trials page: NCT06956339 **possible**, with unknowns turned into questions | "With the questionnaire alone, this ACL trial is *possible*. Most Criteria are unknown, and each becomes a question for the patient or their doctor." |
| 1:20–1:55 | Add the MRI letter → letter review: Facts listed, each Region outlined on the page; enter the missing date; commit | "Now they add their MRI report. Nemotron Parse reads it into Regions, and the Intake agent drafts Facts that each quote one Region. Code, not a model, checks every quote is really on the page. This letter has no date, so the Critic asks, and the patient fills it in." |
| 1:55–2:30 | Trials page after the Re-scan: NCT06956339 **excluded**. Open the reason for inclusion #2, then click the citation and the letter opens with "high grade partial tear… some contiguous fibres" highlighted | "The agent re-checks. Now: excluded. Why? The trial needs a *complete* ACL tear, and the MRI says partial. Click the reason and you're on the exact sentence in the letter." |
| 2:30–3:00 | `docs/samples/3-after-letter-excluded.md` in the browser: the Criterion table, then row #10 with ✗ and the "Retry 2 was asked with" note | "Every claim is checked. Here the Matcher said 'no dislocation' citing a Fact about cartilage wear. The Evaluator, a second Nemotron prompt, rejected it, and on the retry it became unknown. Unsupported claims never reach the patient as a guess." |
| 3:00–3:20 | Zetaris SQL Editor: `SELECT … FROM trialmatch.criterion …` returning rows. Then the Nightshift console request log showing a `nvidia/nemotron-3-ultra-550b-a55b` request | "Agents read only through Zetaris, which federates our World Model's tables. Every model call goes through Meterless Nightshift to Nemotron 3 Ultra, and we log which model answered each one. The patient record is a Meterless World Model, which is how we can say what changed and why." |
| 3:20–3:30 | Closing card: TrialMatch · Track 2 · repo URL | "TrialMatch: trial matching that shows its working." |

**Check after recording:** length between 1:00 and 4:00; scrub every frame for tokens, `.env`, names or addresses;
the audio is audible over any music.
