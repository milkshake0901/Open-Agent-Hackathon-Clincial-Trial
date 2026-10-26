"use client";

// Closed trials listing the patient's Condition term labels (ADR 0004), newest first, in their own section below the Verdicts.
// They can no longer enrol, so they carry no Verdict: only what they studied, their status, when they finished and
// their Outcomes (#25) and who to contact (#27), with an Enquiry about those Outcomes or a follow-on study (#29).
// Nothing is shown until a Diagnosis check has ticked Condition labels (the Condition term, ADR 0005).

import { useEffect, useState } from "react";
import { api, type ClosedTrialOut } from "@/lib/api";
import { Enquiry } from "./enquiry";
import { TrialContacts } from "./trial-contacts";
import { TrialOutcomes } from "./trial-outcomes";

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; term: string[] | null; trials: ClosedTrialOut[] };

const finished = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-AU", { month: "long", year: "numeric" });

export function ClosedTrials({ patientId, versionId }: { patientId: string; versionId: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    api.closedTrials(patientId)
      .then((r) => setState({ kind: "ready", term: r.condition_term, trials: r.trials }))
      .catch((e: Error) => setState({ kind: "error", message: e.message }));
  }, [patientId]);

  if (state.kind === "loading") return null;
  if (state.kind === "error")
    return <p role="alert" className="text-red-700 dark:text-red-400">Past trials could not be loaded: {state.message}</p>;
  if (state.term === null || state.trials.length === 0) return null;

  return (
    <section aria-labelledby="closed-trials" className="flex flex-col gap-3">
      <h2 id="closed-trials" className="text-lg font-semibold">Past trials for {state.term.join(", ")}</h2>
      <p className="text-muted">
        These trials have stopped taking new people, so we have not checked them against your answers. They show what
        research has already been done in Australia. Newest first.
      </p>
      {state.trials.map((t) => (
        <article key={t.nct_id} className="rounded-xl border border-border bg-surface p-5 flex flex-col gap-1">
          <h3 className="font-semibold">{t.title}</h3>
          <p className="text-sm text-muted">
            <a href={t.url} className="underline" rel="noreferrer" target="_blank">{t.nct_id}</a>
            {" · "}{t.status.toLowerCase().replaceAll("_", " ")}
            {t.closed_on && ` · finished ${finished(t.closed_on)}`}
          </p>
          <TrialOutcomes nctId={t.nct_id} />
          <TrialContacts nctId={t.nct_id} />
          <Enquiry patientId={patientId} versionId={versionId} nctId={t.nct_id} open={false} />
        </article>
      ))}
    </section>
  );
}
