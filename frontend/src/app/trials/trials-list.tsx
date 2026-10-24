"use client";

// Ranked Verdicts for one Profile version, as the backend returns them (eligible, possible with fewest unknowns
// first, excluded). Each Criterion shows its result, the one-line rationale and its Citation; a Citation from the
// questionnaire links back to that question.

import { useEffect, useState } from "react";
import { api, type CriterionResultOut, type DoctorQuestion, type VerdictOut } from "@/lib/api";

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; verdicts: VerdictOut[]; questions: DoctorQuestion[] };

const GROUPS: { outcome: VerdictOut["outcome"]; title: string; blurb: string }[] = [
  { outcome: "eligible", title: "Likely a fit", blurb: "Everything we could check matches. The trial team will still confirm." },
  { outcome: "possible", title: "May be a fit", blurb: "Some things need checking with your doctor." },
  { outcome: "excluded", title: "Probably not a fit", blurb: "Something you told us rules this trial out." },
];

const RESULT_LABEL: Record<CriterionResultOut["outcome"], string> = {
  met: "Matches",
  not_met: "Does not match",
  unknown: "Needs checking",
};

export function TrialsList({ patientId, versionId }: { patientId: string; versionId: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    Promise.all([api.verdicts(patientId, versionId), api.doctorQuestions(patientId, versionId)])
      .then(([v, questions]) => setState({ kind: "ready", verdicts: v.verdicts, questions }))
      .catch((e: Error) => setState({ kind: "error", message: e.message }));
  }, [patientId, versionId]);

  if (state.kind === "loading") return <p className="text-muted">Checking trials…</p>;
  if (state.kind === "error")
    return <p role="alert" className="text-red-700 dark:text-red-400">Trials could not be loaded: {state.message}</p>;
  if (state.verdicts.length === 0)
    return <p>No trials have been checked against these answers yet. Please try again in a few minutes.</p>;

  return (
    <div className="flex flex-col gap-8">
      {GROUPS.map((g) => {
        const verdicts = state.verdicts.filter((v) => v.outcome === g.outcome);
        if (verdicts.length === 0) return null;
        return (
          <section key={g.outcome} aria-labelledby={`group-${g.outcome}`} className="flex flex-col gap-3">
            <h2 id={`group-${g.outcome}`} className="text-lg font-semibold">{g.title}</h2>
            <p className="text-muted">{g.blurb}</p>
            {verdicts.map((v) => <VerdictCard key={v.nct_id} verdict={v} />)}
          </section>
        );
      })}
      {state.questions.length > 0 && (
        <section aria-labelledby="doctor-questions" className="rounded-xl border border-border bg-surface p-5 flex flex-col gap-3">
          <h2 id="doctor-questions" className="text-lg font-semibold">Questions for your doctor</h2>
          <p className="text-muted">These need the patient&apos;s medical records. Take this list to the next appointment.</p>
          <ol className="flex flex-col gap-2 list-decimal pl-5">
            {state.questions.map((q) => (
              <li key={q.criterion_id ?? q.subject}>
                {q.text}
                <span className="block text-sm text-muted">
                  {q.criterion_id === null
                    ? "Helps us search for the right trials"
                    : `Helps decide ${q.unblocks.length} trial${q.unblocks.length === 1 ? "" : "s"}`}
                </span>
              </li>
            ))}
          </ol>
        </section>
      )}
    </div>
  );
}

function VerdictCard({ verdict: v }: { verdict: VerdictOut }) {
  const unknown = v.results.filter((r) => r.outcome === "unknown").length;
  return (
    <article className="rounded-xl border border-border bg-surface p-5 flex flex-col gap-3">
      <header className="flex flex-col gap-1">
        <h3 className="font-semibold">{v.title}</h3>
        <p className="text-sm text-muted">
          <a href={`https://clinicaltrials.gov/study/${v.nct_id}`} className="underline" rel="noreferrer" target="_blank">
            {v.nct_id}
          </a>
          {" · "}{v.status.toLowerCase().replaceAll("_", " ")}
          {unknown > 0 && ` · ${unknown} thing${unknown === 1 ? "" : "s"} to check`}
        </p>
        {v.degraded && (
          <p className="text-sm text-muted">Some answers could not be confirmed, so they are marked as needing checking.</p>
        )}
      </header>
      <details>
        <summary className="cursor-pointer min-h-11 flex items-center text-accent">Why</summary>
        <ul className="flex flex-col gap-3 mt-2">
          {v.results.map((r) => <ResultItem key={r.criterion_id} result={r} />)}
        </ul>
      </details>
    </article>
  );
}

function ResultItem({ result: r }: { result: CriterionResultOut }) {
  return (
    <li className="rounded-lg border border-border p-3 flex flex-col gap-1">
      <p className="text-sm text-muted">{r.kind === "inclusion" ? "Needed" : "Rules out"}: {r.text}</p>
      <p className="font-medium">{RESULT_LABEL[r.outcome]}</p>
      <p>{r.rationale}</p>
      {r.citation && (
        <p className="text-sm">
          {r.citation.question ? (
            <a href={`/#${r.citation.question}`} className="text-accent underline">
              You told us (intake questionnaire, {r.citation.question})
            </a>
          ) : (
            <span className="text-muted">{r.citation.label}</span>
          )}
          : “{r.citation.quote}”
        </p>
      )}
    </li>
  );
}
