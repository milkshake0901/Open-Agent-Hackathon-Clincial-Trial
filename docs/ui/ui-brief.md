# UI brief: TrialMatch web app

For the agent building the frontend. Read this first, then [GLOSSARY.md](../../GLOSSARY.md) (use its terms exactly in code and copy), [docs/api.md](../api.md) (existing endpoints) and [ADR 0003](../adr/0003-intake-questionnaire-is-a-document.md). The page list in [frontend/README.md](../../frontend/README.md) still holds; this brief adds the Intake questionnaire and pins down behaviour.

Status: the backend is a scaffold (bodies raise `NotImplementedError`). Build against a mock of the endpoints below; generate types from `http://localhost:8000/openapi.json` once it runs. Endpoints marked **(new)** are not in `docs/api.md` yet: treat their shapes as the proposed contract and flag anything you need changed instead of working around it.

## Who uses it

The **Respondent**: a patient with cancer, or a family member or carer answering on their behalf. Often anxious, often on a phone, not medically trained. Plain language, large tap targets, no jargon without an explanation, nothing that reads like a verdict on their prognosis.

## Stack and constraints

- Next.js (App Router), TypeScript, created in `frontend/` with `npx create-next-app@latest .`.
- Web first. Keep the questionnaire **driven by a definition fetched from the backend**, rendered by a generic renderer, so the same definition can later drive a one-question-at-a-time chat bot (WhatsApp/Telegram). Do not hard-code questions in components.
- Mobile-first layout; works at 360px wide.
- Accessibility: labels on every input, keyboard navigable, WCAG AA contrast.

## Privacy rules (non-negotiable)

- Never ask for name, full date of birth, street address or Medicare number.
- Postcode is only ever sent to the backend; never display it back in results, never put it in a URL.
- No patient data in URLs or query strings except opaque ids and the return-link token.
- No analytics or third-party scripts.

## Flow

1. **Welcome** — what TrialMatch does, that it does not replace their doctor, roughly 10 minutes, can be saved and resumed.
2. **Who is answering** — "I'm the patient" / "I'm answering for someone else". The choice switches wording ("your" ↔ "their") throughout.
3. **Intake questionnaire** — sections below, one section per screen, progress indicator, back/next, answers kept if they go back.
4. **Diagnosis check** — show the condition term the backend suggests from their free text: "We understood this as *non-small cell lung cancer*. Is that right?" Yes / No, let me re-word / Not sure. "Not sure" is fine and should say we'll suggest asking their GP.
5. **Optional uploads** — "Have letters or reports? Adding them makes results more accurate." Multi-file upload, skippable. Each file becomes its own Document and Profile version; show one "Checking 3 documents…" progress state, not three separate results.
6. **Return link** — show a private link to come back, with copy button; optional email or phone for "you have new questions" notices, clearly marked optional.
7. **Results** (existing Trials page) — see below.

## Questionnaire sections

| Section | Questions | Input |
|---|---|---|
| About | Birth year and month; Sex assigned at birth (Female / Male / Intersex / Prefer not to say) | month+year picker; radio |
| Where | Postcode; How far would you travel for a trial? (10 / 25 / 50 / 100 km / Anywhere in Australia) | text (4 digits); radio |
| Diagnosis | What is the diagnosis, in your own words? When was it diagnosed? | textarea; free text ("around March 2024" is fine) |
| Treatment so far | Treatments had (chemo, radiotherapy, surgery, immunotherapy, targeted therapy, other), each with roughly when and whether it's ongoing | repeatable rows, free-text dates |
| Medicines now | Current medicines | repeatable free text |
| Allergies | Any allergies? | yes/no + free text |
| Other health | Other major illnesses (heart, kidney, liver, infections, other) | checkboxes + free text |
| Daily activity | Which best describes a usual day? (5 plain-language options from "fully active" to "in bed most of the day") | radio |
| Pregnancy | Currently pregnant, breastfeeding or planning a pregnancy? (optional) | Yes / No / Prefer not to say |

Free-text date fields must accept vague answers; never force an exact date. Every question except birth month, sex, postcode and diagnosis is optional. These are the defaults; the backend definition is the source of truth.

## Results and follow-up

- **Trials list**: grouped by Verdict (eligible, possible, excluded), then sorted by nearest recruiting site. Show "Westmead Hospital · recruiting · 23 km". Trials beyond the travel limit go under a collapsed **Further away** heading; never hide them.
- Verdict wording must be careful: "possible" = "may be a fit; some things need checking", never "you qualify".
- **Verdict detail**: each Criterion with met / not met / unknown, the one-line rationale and its Citation. A Citation from the questionnaire reads "You told us (intake questionnaire, Q4)"; from a Document it opens the de-identified page.
- **Two question lists, kept visually separate**:
  - **Questions for you** (Respondent questions): answerable inline; submitting creates a new questionnaire submission and a new Profile version.
  - **Questions for your doctor** (Doctor questions): printable/shareable list, deduplicated, each showing how many Trials it would unblock.
- **Conflict dialog** (existing): when an answer contradicts a document, show both sides with their source and let them choose.
- **What changed**: after a new version, highlight Verdicts that moved and why ("v1 from your answers → v2 after the genomic report").
- **Edit answers**: reopen the questionnaire pre-filled; saving resubmits the whole thing.

## Endpoints

Existing (see `docs/api.md`): `POST /patients`, `POST /patients/{pid}/documents`, `GET /patients/{pid}/versions`, `GET .../versions/{vid}/verdicts`, `GET .../verdicts/{nct}`, `GET .../diff`, `GET /patients/{pid}/questions`, `GET /runs/{run_id}/events` (poll ~1 s), `POST /runs/{run_id}/confirm`.

Proposed **(new)**:

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/questionnaire/definition` | | `{version, sections: [{id, title, questions: [{id, label, label_other, kind: "month_year"\|"single"\|"multi"\|"text"\|"textarea"\|"repeat", options?, required, help?}]}]}` (`label_other` is the "their" wording) |
| POST | `/patients/{pid}/questionnaire` | `{definition_version, respondent: "patient"\|"other", answers: {question_id: value}}` | `202 {document_hash, run_id, return_token}` |
| GET | `/patients/{pid}/questionnaire` | | latest answers, for pre-filling edits |
| POST | `/patients/{pid}/questionnaire/diagnosis-check` | `{text}` | `{suggested_term, confidence}` |
| PUT | `/patients/{pid}/search-preferences` | `{postcode, max_travel_km}` | `204` |
| GET | `/patients/{pid}/respondent-questions?version={vid}` | | `[{id, text, question_id?, nct_ids[]}]` |
| GET | `/return/{token}` | | `{patient_id}` (resumes the session) |

Verdict list items gain `nearest_site: {name, status, km} | null` and `further_away: bool`.

## Out of scope

Accounts and passwords, sending notifications, the chat-bot channel, the Why/trace page polish, any clinician-facing view.
