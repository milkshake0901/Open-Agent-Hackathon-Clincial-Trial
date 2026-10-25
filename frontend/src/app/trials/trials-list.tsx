"use client";

// Ranked Verdicts for one Profile version, as the backend returns them (eligible, possible with fewest unknowns
// first, excluded; then nearest recruiting site). Trials with no recruiting site within the travel limit sit in a
// collapsed "Further away" group under their outcome, never hidden. Each Criterion shows its result, the one-line rationale and its Citation; a Citation from the
// questionnaire links back to that question. Each Trial offers its contacts and an Enquiry to copy and send. Questions for you (Respondent questions, answered inline) and
// Questions for your doctor are kept as two separate lists.

import { useEffect, useState } from "react";
import {
  api, type CriterionResultOut, type DoctorQuestion, type RespondentQuestion, type SiteOut, type VerdictOut,
} from "@/lib/api";
import { QuestionsForYou } from "./questions-for-you";
import { Enquiry } from "./enquiry";
import { TrialContacts } from "./trial-contacts";

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; verdicts: VerdictOut[]; questions: DoctorQuestion[]; asked: RespondentQuestion[] };

const GROUPS: { outcome: VerdictOut["outcome"]; title: string; blurb: string }[] = [
  { outcome: "eligible", title: "Likely a fit", blurb: "Everything we could check matches. The trial team will still confirm." },
  { outcome: "possible", title: "May be a fit", blurb: "Some things need checking with you or your doctor." },
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
    Promise.all([api.verdicts(patientId, versionId), api.doctorQuestions(patientId, versionId),
                 api.respondentQuestions(patientId, versionId)])
      .then(([v, questions, asked]) => setState({ kind: "ready", verdicts: v.verdicts, questions, asked }))
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
        const near = verdicts.filter((v) => !v.further_away);
        const far = verdicts.filter((v) => v.further_away);
        return (
          <section key={g.outcome} aria-labelledby={`group-${g.outcome}`} className="flex flex-col gap-3">
            <h2 id={`group-${g.outcome}`} className="text-lg font-semibold">{g.title}</h2>
            <p className="text-muted">{g.blurb}</p>
            {near.map((v) => <VerdictCard key={v.nct_id} verdict={v} patientId={patientId} versionId={versionId} />)}
            {far.length > 0 && (
              <details className="flex flex-col gap-3">
                <summary className="cursor-pointer min-h-11 flex items-center text-accent">
                  Further away ({far.length})
                </summary>
                <p className="text-muted">No site is recruiting within the distance you said you would travel.</p>
                <div className="flex flex-col gap-3 mt-2">
                  {far.map((v) => <VerdictCard key={v.nct_id} verdict={v} patientId={patientId} versionId={versionId} />)}
                </div>
              </details>
            )}
          </section>
        );
      })}
      {state.asked.length > 0 && <QuestionsForYou patientId={patientId} questions={state.asked} />}
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

function VerdictCard({ verdict: v, patientId, versionId }: { verdict: VerdictOut; patientId: string; versionId: string }) {
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
        <SiteLines verdict={v} />
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
      <TrialContacts nctId={v.nct_id} />
      <Enquiry patientId={patientId} versionId={versionId} nctId={v.nct_id} />
    </article>
  );
}

const siteLine = (s: SiteOut) => `${s.name} · ${s.status} · ${s.km === null ? "distance unknown" : `${s.km} km`}`;

function SiteLines({ verdict: v }: { verdict: VerdictOut }) {
  // The nearest recruiting site, plus any closer site that is not recruiting yet (so a nearby site that has not
  // opened is shown honestly, not as an option today).
  const closer = v.sites.filter(
    (s) => s.status !== "recruiting" && s.km !== null && (v.nearest_site?.km == null || s.km < v.nearest_site.km),
  );
  return (
    <ul className="text-sm flex flex-col gap-0.5">
      {v.nearest_site ? <li>{siteLine(v.nearest_site)}</li> : <li className="text-muted">No site is recruiting yet</li>}
      {closer.slice(0, 2).map((s) => (
        <li key={s.name} className="text-muted">{siteLine(s)}</li>
      ))}
    </ul>
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
