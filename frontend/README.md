# Frontend (Next.js, not scaffolded yet)

Create with `npx create-next-app@latest .` once the API runs. Generate API types from
`http://localhost:8000/openapi.json`.

Pages, each backed by endpoints in `docs/api.md`:
- **Record**: upload Documents, Profile version timeline, Conflict dialog.
- **Trials**: ranked Verdicts per version, Verdict detail with Citations that open the source page.
- **What changed**: Verdict changes between two versions (the demo moment).
- **Why**: the causal trace of a run, with which model answered each step.
- **Doctor questions**: deduplicated across Trials.
