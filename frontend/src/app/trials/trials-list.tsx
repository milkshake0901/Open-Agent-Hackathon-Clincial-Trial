"use client";

// Ranked Verdicts for one Profile version, as the backend returns them (eligible, possible with fewest unknowns
// first, excluded; then nearest recruiting site). Trials with no recruiting site within the travel limit sit in a
// collapsed "Further away" group under their outcome, never hidden. Each Criterion shows its result, the one-line rationale and its Citation; a Citation from the
// questionnaire opens a side panel with the question and the answer, the quote highlighted, and one from a letter opens it with the page and its Region boxed
// (as does each Context Fact listed under an unknown reason). Each recruiting Trial takes a free-form question, whose
// cited Regions open in the same kind of side panel. Each Trial offers its contacts and an Enquiry to copy and send (about
// taking part, or about its results once it is no longer recruiting). Questions for you (Respondent questions, answered inline) and
// Questions for your doctor are kept as two separate lists. A Trial that stopped recruiting after it was judged keeps
// its Verdict, shown in its own "No longer recruiting" section after the open ones (ADR 0004). Only Trials listing a
// Condition label the Respondent ticked are judged and listed, and the page names those labels; until some are ticked
// (the Condition term, ADR 0005) it asks the Respondent to finish the diagnosis step instead.

import { useEffect, useState } from "react";
import {
  api, type CriterionResultOut, type Diagnosis, type DoctorQuestion, type RespondentQuestion, type SiteOut,
  type VerdictCitation, type VerdictOut,
} from "@/lib/api";
import { checkedLabel, CitationSource, hasSource, sourceLabel } from "@/app/citation-source";
import { QuestionsForYou } from "./questions-for-you";
import { Enquiry } from "./enquiry";
import { TrialContacts } from "./trial-contacts";
import { TrialQuestion } from "./trial-question";

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | {
      kind: "ready"; term: string[] | null; diagnosis: Diagnosis; verdicts: VerdictOut[]; questions: DoctorQuestion[];
      asked: RespondentQuestion[];
    };

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
      .then(([v, questions, asked]) =>
        setState({
          kind: "ready", term: v.condition_term, diagnosis: v.diagnosis, verdicts: v.verdicts, questions, asked,
        }))
      .catch((e: Error) => setState({ kind: "error", message: e.message }));
  }, [patientId, versionId]);

  if (state.kind === "loading") return <p className="text-muted">Checking trials…</p>;
  if (state.kind === "error")
    return <p role="alert" className="text-red-700 dark:text-red-400">Trials could not be loaded: {state.message}</p>;
  if (state.term === null)
    return (
      <div className="flex flex-col gap-8">
        <section aria-labelledby="finish-diagnosis" className="rounded-xl border border-border bg-surface p-5 flex flex-col gap-3">
          <h2 id="finish-diagnosis" className="text-lg font-semibold">First, finish the diagnosis step</h2>
          <p>
            We only check trials for the conditions you tick in the diagnosis step, so no trials have been checked yet.
            {state.diagnosis === "not_sure"
              ? " You told us you are not sure of the diagnosis: once the GP has confirmed its name, go back and tick the conditions that match it."
              : " Go back to your answers and tick the conditions that match the diagnosis, as trials name them."}
          </p>
          {/* Back, not a link: "/" restores no patient (their id lives only in that page's state, and the return
              link opens their record, not the diagnosis step), so a link would start a new questionnaire. */}
          <button type="button" onClick={() => window.history.back()}
                  className="self-start min-h-12 rounded-lg border border-border px-5 text-base font-semibold">
            Back to the diagnosis step
          </button>
        </section>
        <DoctorQuestions questions={state.questions} />
      </div>
    );

  const none = state.verdicts.length === 0;
  const closed = state.verdicts.filter((v) => v.no_longer_recruiting);
  return (
    <div className={`flex flex-col ${none ? "gap-3" : "gap-8"}`}>
      <p className="text-muted">Trials for {state.term.join(", ")}, the conditions you ticked in the diagnosis step.</p>
      {none ? (
        <p>No trials have been checked against these answers yet. Please try again in a few minutes.</p>
      ) : (
        <>
          {GROUPS.map((g) => {
            const verdicts = state.verdicts.filter((v) => v.outcome === g.outcome && !v.no_longer_recruiting);
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
          {closed.length > 0 && (
            <section aria-labelledby="group-no-longer-recruiting" className="flex flex-col gap-3">
              <h2 id="group-no-longer-recruiting" className="text-lg font-semibold">No longer recruiting</h2>
              <p className="text-muted">
                These trials stopped recruiting after we checked them. Your earlier result is kept so you can see what it
                was, but they are not checked again.
              </p>
              {closed.map((v) => <VerdictCard key={v.nct_id} verdict={v} patientId={patientId} versionId={versionId} />)}
            </section>
          )}
          {state.asked.length > 0 && <QuestionsForYou patientId={patientId} questions={state.asked} />}
          <DoctorQuestions questions={state.questions} />
        </>
      )}
    </div>
  );
}

function DoctorQuestions({ questions }: { questions: DoctorQuestion[] }) {
  if (questions.length === 0) return null;
  return (
    <section aria-labelledby="doctor-questions" className="rounded-xl border border-border bg-surface p-5 flex flex-col gap-3">
      <h2 id="doctor-questions" className="text-lg font-semibold">Questions for your doctor</h2>
      <p className="text-muted">These need the patient&apos;s medical records. Take this list to the next appointment.</p>
      <ol className="flex flex-col gap-2 list-decimal pl-5">
        {questions.map((q) => (
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
  );
}

function VerdictCard({ verdict: v, patientId, versionId }: { verdict: VerdictOut; patientId: string; versionId: string }) {
  const unknown = v.results.filter((r) => r.outcome === "unknown").length;
  return (
    <article className="rounded-xl border border-border bg-surface p-5 flex flex-col gap-3">
      <header className="flex flex-col gap-1">
        <h3 className="font-semibold">{v.title}</h3>
        {v.no_longer_recruiting && (
          <p className="text-sm font-medium">
            No longer recruiting. When we checked, this trial was{" "}
            {GROUPS.find((g) => g.outcome === v.outcome)?.title.toLowerCase()}.
          </p>
        )}
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
      {!v.no_longer_recruiting && <TrialQuestion patientId={patientId} nctId={v.nct_id} />}
      <TrialContacts nctId={v.nct_id} />
      <Enquiry patientId={patientId} versionId={versionId} nctId={v.nct_id} open={!v.no_longer_recruiting} />
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
  const [open, setOpen] = useState(false);
  return (
    <li className="rounded-lg border border-border p-3 flex flex-col gap-1">
      <p className="text-sm text-muted">{r.kind === "inclusion" ? "Needed" : "Rules out"}: {r.text}</p>
      <p className="font-medium">{RESULT_LABEL[r.outcome]}</p>
      <p>{r.rationale}</p>
      {r.citation && (
        <p className="text-sm">
          {r.citation.question ? (
            <span className="text-muted">You told us (intake questionnaire, {r.citation.question})</span>
          ) : (
            <span className="text-muted">{r.citation.filename ? `${r.citation.filename}, ` : ""}{r.citation.label}</span>
          )}
          : “{r.citation.quote}”
          {checkedLabel(r.citation) && <span className="text-muted"> ({checkedLabel(r.citation)})</span>}
        </p>
      )}
      {r.citation && hasSource(r.citation) && (
        <button type="button" onClick={() => setOpen(true)}
                className="min-h-11 self-start rounded-lg border border-border px-4 text-sm font-semibold text-accent">
          {sourceLabel(r.citation)}
        </button>
      )}
      {r.citation && hasSource(r.citation) && open && (
        <CitationPanel result={r} citation={r.citation} onClose={() => setOpen(false)} />
      )}
      {r.context_facts.length > 0 && <ContextFacts result={r} />}
    </li>
  );
}

// Under an unknown reason: the Context Facts it considered, each opening its source in the side panel.
function ContextFacts({ result: r }: { result: CriterionResultOut }) {
  const [opened, setOpened] = useState<VerdictCitation | null>(null);
  return (
    <div className="mt-1 flex flex-col gap-1">
      <p className="text-sm font-medium">What we looked at, which doesn&apos;t settle it:</p>
      <ul className="flex flex-col gap-2">
        {r.context_facts.map((c) => (
          <li key={c.fact_id} className="text-sm flex flex-col gap-1">
            <p>
              <span className="text-muted">{c.filename ? `${c.filename}, ` : ""}{c.label}</span>: “{c.quote}”
            </p>
            {hasSource(c) && (
              <button type="button" onClick={() => setOpened(c)}
                      className="min-h-11 self-start rounded-lg border border-border px-4 text-sm font-semibold text-accent">
                {sourceLabel(c)}
              </button>
            )}
          </li>
        ))}
      </ul>
      {opened && <CitationPanel result={r} citation={opened} onClose={() => setOpened(null)} />}
    </div>
  );
}

// The side panel a Criterion result opens: what its Citation points at, the letter page with the Region boxed or the
// questionnaire answer with the quote highlighted.
function CitationPanel({ result: r, citation: c, onClose }: {
  result: CriterionResultOut;
  citation: VerdictCitation;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <button type="button" aria-label="Close" onClick={onClose} className="absolute inset-0 bg-black/30" />
      <aside role="dialog" aria-modal="true" aria-labelledby={`panel-${r.criterion_id}`}
             className="relative z-50 h-full w-full max-w-xl overflow-y-auto bg-surface border-l border-border p-4 sm:p-5 flex flex-col gap-3">
        <div className="flex items-start justify-between gap-3">
          <h2 id={`panel-${r.criterion_id}`} className="text-lg font-semibold">{RESULT_LABEL[r.outcome]}</h2>
          <button type="button" onClick={onClose}
                  className="min-h-11 rounded-lg border border-border px-4 text-sm font-semibold">Close</button>
        </div>
        <p className="text-sm text-muted">{r.kind === "inclusion" ? "Needed" : "Rules out"}: {r.text}</p>
        <p>{r.rationale}</p>
        <CitationSource citation={c} />
      </aside>
    </div>
  );
}
