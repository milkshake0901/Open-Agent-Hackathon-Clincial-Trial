"use client";

// A Trial's Outcomes (#25): its planned outcome measures, its posted results if it has any, and the publications
// linked to it. Loaded from the Trial detail when first opened.

import { useState } from "react";
import { api, type OutcomeMeasureOut, type OutcomesOut, type PostedResultOut } from "@/lib/api";

type State = { kind: "closed" } | { kind: "loading" } | { kind: "error"; message: string } | { kind: "ready"; outcomes: OutcomesOut };

const words = (code: string) => code.toLowerCase().replaceAll("_", " ");

export function TrialOutcomes({ nctId }: { nctId: string }) {
  const [state, setState] = useState<State>({ kind: "closed" });

  function load() {
    if (state.kind !== "closed") return;
    setState({ kind: "loading" });
    api.trial(nctId)
      .then((trial) => setState({ kind: "ready", outcomes: trial.outcomes }))
      .catch((e: Error) => setState({ kind: "error", message: e.message }));
  }

  return (
    <details onToggle={(e) => e.currentTarget.open && load()}>
      <summary className="cursor-pointer min-h-11 flex items-center text-accent">What it measured and found</summary>
      {state.kind === "loading" && <p className="text-muted">Loading outcomes…</p>}
      {state.kind === "error" && (
        <p role="alert" className="text-red-700 dark:text-red-400">Outcomes could not be loaded: {state.message}</p>
      )}
      {state.kind === "ready" && <OutcomeList outcomes={state.outcomes} />}
    </details>
  );
}

function OutcomeList({ outcomes: o }: { outcomes: OutcomesOut }) {
  const planned: [string, OutcomeMeasureOut[]][] = [
    ["Main things measured", o.primary],
    ["Other things measured", [...o.secondary, ...o.other]],
  ];
  return (
    <div className="flex flex-col gap-4 mt-2 text-sm">
      {planned.filter(([, ms]) => ms.length > 0).map(([label, ms]) => (
        <section key={label} className="flex flex-col gap-1">
          <h4 className="font-medium">{label}</h4>
          <ul className="flex flex-col gap-1 list-disc pl-5">
            {ms.map((m, i) => (
              <li key={i}>
                {m.measure}
                {m.time_frame && <span className="text-muted"> ({m.time_frame})</span>}
                {m.description && <p className="text-muted">{m.description}</p>}
              </li>
            ))}
          </ul>
        </section>
      ))}
      <section className="flex flex-col gap-2">
        <h4 className="font-medium">Results</h4>
        {o.results.length === 0
          ? <p className="text-muted">{o.has_results ? "Results are posted on ClinicalTrials.gov." : "No results have been posted yet."}</p>
          : o.results.map((r, i) => <Result key={i} result={r} />)}
      </section>
      {o.publications.length > 0 && (
        <section className="flex flex-col gap-1">
          <h4 className="font-medium">Publications</h4>
          <ul className="flex flex-col gap-2">
            {o.publications.map((p, i) => (
              <li key={i}>
                {p.citation}
                {p.type === "RESULT" && <span className="text-muted"> (reports this trial&apos;s results)</span>}
                {p.url && <> · <a href={p.url} className="text-accent underline" rel="noreferrer" target="_blank">PubMed</a></>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function Result({ result: r }: { result: PostedResultOut }) {
  const spread = (v: PostedResultOut["values"][number]) =>
    v.lower || v.upper ? ` (${v.lower} to ${v.upper})` : v.spread ? ` (± ${v.spread})` : "";
  return (
    <div className="rounded-lg border border-border p-3 flex flex-col gap-1">
      <p>
        {r.title}
        <span className="text-muted"> · {words(r.type)}{r.param_type && `, ${words(r.param_type)}`}{r.time_frame && `, ${r.time_frame}`}</span>
      </p>
      {r.description && <p className="text-muted">{r.description}</p>}
      {r.values.length > 0 && (
        <ul className="flex flex-col gap-0.5">
          {r.values.map((v, i) => (
            <li key={i}>
              {v.group}{v.label && <span className="text-muted"> · {v.label}</span>}: {v.value}{r.unit && ` ${r.unit}`}{spread(v)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
