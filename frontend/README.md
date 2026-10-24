# Frontend (Next.js)

Created with `create-next-app@16.4.3` (App Router, TypeScript, Tailwind). Runs on **port 3001**,
because the Zetaris UI uses 3000. `/api/*` is proxied to FastAPI (`TRIALMATCH_API_URL`, default
`http://localhost:8000`), so the browser talks to one origin and the backend needs no CORS.

    npm install
    npm run dev            # http://localhost:3001

Today the home page renders the Intake questionnaire from `GET /api/questionnaire/definition` with a
generic renderer (no hard-coded questions), submits it, and shows Profile v1 with each Fact's Citation.
Wire types are hand-written in `src/lib/api.ts`; generate them from `http://localhost:8000/openapi.json`
once more pages exist.

Pages still to build, each backed by endpoints in `docs/api.md`:
- **Record**: upload Documents, Profile version timeline, Conflict dialog.
- **Trials**: ranked Verdicts per version, Verdict detail with Citations that open the source page.
- **What changed**: Verdict changes between two versions (the demo moment).
- **Why**: the causal trace of a run, with which model answered each step.
- **Doctor questions**: deduplicated across Trials.
