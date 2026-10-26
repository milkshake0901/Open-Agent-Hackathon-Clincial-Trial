"use client";

// A free-form question of one Trial, asked from its Verdict on the Trials page (#52). The model reads this Trial's
// Criteria and the Regions of every Document the Respondent added, for any condition. Each Region its answer cites
// opens in the side panel: the page image with that Region boxed. The answer lives only in this page: it is not saved
// and never changes a Verdict.

import { useEffect, useState } from "react";
import { api, type GroundedCitation, type TrialAsk } from "@/lib/api";
import { RegionPage } from "@/app/region-page";

const ASK_MS = 60_000;
const SUGGESTED = ["Am I eligible?", "What should I gather before applying?"];

const STANDING: Record<TrialAsk["standing"], string> = {
  eligible: "Looks eligible from your documents",
  possible: "Possibly a fit",
  excluded: "Your documents appear to rule this out",
  needs_information: "More information is needed",
};

function askFraction(elapsedMs: number): number {
  return Math.min(0.9, 0.08 + (elapsedMs / ASK_MS) * 0.82);
}

// The ask needs a Document read into Regions; with none the backend answers 404 "... has no parsed letter".
function plainError(message: string): string {
  return message.includes("no parsed letter")
    ? "Add a letter or report to your answers first: the question is answered from your documents."
    : message;
}

export function TrialQuestion({ patientId, nctId }: { patientId: string; nctId: string }) {
  const [question, setQuestion] = useState(SUGGESTED[0]);
  const [pending, setPending] = useState(false);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [answer, setAnswer] = useState<TrialAsk | null>(null);
  const [opened, setOpened] = useState<GroundedCitation | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!pending) return;
    const started = performance.now();
    const id = window.setInterval(() => setElapsedMs(performance.now() - started), 200);
    return () => window.clearInterval(id);
  }, [pending]);

  async function onAsk(text: string) {
    const asked = text.trim();
    if (!asked || pending) return;
    setQuestion(asked);
    setPending(true);
    setElapsedMs(0);
    setAnswer(null);
    setOpened(null);
    setError(null);
    try {
      setAnswer(await api.askTrial(patientId, nctId, asked));
    } catch (err) {
      setError(plainError((err as Error).message));
    } finally {
      setPending(false);
    }
  }

  return (
    <details>
      <summary className="cursor-pointer min-h-11 flex items-center text-accent">Ask a question of this trial</summary>
      <form className="flex flex-col gap-3 mt-2" onSubmit={(e) => { e.preventDefault(); void onAsk(question); }}>
        <div className="flex flex-wrap gap-2">
          {SUGGESTED.map((prompt) => (
            <button key={prompt} type="button" disabled={pending} onClick={() => void onAsk(prompt)}
                    className="min-h-11 rounded-lg border border-border px-3 text-sm font-semibold disabled:opacity-60">
              {prompt}
            </button>
          ))}
        </div>
        <label className="flex flex-col gap-1 text-sm">
          Your question
          <input value={question} onChange={(e) => setQuestion(e.target.value)} disabled={pending} maxLength={500}
                 className="min-h-11 rounded-md border border-border bg-transparent px-3 py-2 text-base" />
        </label>
        <button type="submit" disabled={pending || !question.trim()}
                className="min-h-11 self-start rounded-lg bg-accent px-4 text-sm font-semibold text-white dark:text-black disabled:opacity-60">
          {pending ? "Reading your documents and the criteria…" : "Ask"}
        </button>
        {pending && (
          <div className="flex flex-col gap-2">
            <div role="progressbar" aria-valuemin={0} aria-valuemax={100}
                 aria-valuenow={Math.round(askFraction(elapsedMs) * 100)}
                 aria-valuetext={`Reading your documents and the criteria, ${Math.floor(elapsedMs / 1000)} seconds`}
                 className="h-1.5 overflow-hidden rounded-full bg-border">
              <div className="h-full rounded-full bg-accent transition-[width] duration-200 ease-linear"
                   style={{ width: `${askFraction(elapsedMs) * 100}%` }} />
            </div>
            <p className="text-sm text-muted">Reading your documents and the criteria, {Math.floor(elapsedMs / 1000)}s</p>
          </div>
        )}
        {error && <p role="alert" className="text-sm text-red-700 dark:text-red-400">{error}</p>}
        {answer && (
          <div className="flex flex-col gap-2 text-sm" aria-live="polite">
            <p className="font-semibold">{STANDING[answer.standing]}</p>
            <p>{answer.answer}</p>
            {answer.to_gather.length > 0 && (
              <div>
                <p className="font-medium">Still to gather</p>
                <ul className="list-disc pl-5">
                  {answer.to_gather.map((line) => <li key={line}>{line}</li>)}
                </ul>
              </div>
            )}
            {answer.misses.length > 0 && (
              <div className="flex flex-col gap-2">
                <p className="font-medium">Exclusion criteria your documents show</p>
                <ul className="flex flex-col gap-2">
                  {answer.misses.map((miss) => (
                    <li key={miss.criterion_id}>
                      <button type="button" onClick={() => setOpened(miss.citation)}
                              className="min-h-11 w-full rounded-md border border-border px-3 py-2 text-left">
                        <span className="block font-medium">{miss.clause}</span>
                        {miss.why && <span className="mt-1 block">{miss.why}</span>}
                        <span className="mt-1 block text-accent">Show page {miss.citation.page}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {answer.citations.length > 0 && (
              <div className="flex flex-col gap-2">
                <p className="font-medium">Where your documents say this</p>
                <ul className="flex flex-col gap-2">
                  {answer.citations.map((c) => (
                    <li key={c.span_id}>
                      <button type="button" onClick={() => setOpened(c)}
                              className="min-h-11 w-full rounded-md border border-border px-3 py-2 text-left">
                        <span className="block">“{c.quote}”</span>
                        <span className="mt-1 block text-accent">{c.filename}, page {c.page}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <p className="text-muted">Read through {answer.via === "zetaris" ? "Zetaris" : "Postgres"}. Not saved.</p>
          </div>
        )}
      </form>
      {answer && opened && (
        <RegionPanel answer={answer} opened={opened} onSelect={setOpened} onClose={() => setOpened(null)} />
      )}
    </details>
  );
}

// The same side panel a Criterion result's Citation opens: the page the cited Region is on, with every Region the
// answer cites on that page boxed and the chosen one shaded.
function RegionPanel({ answer, opened, onSelect, onClose }: {
  answer: TrialAsk;
  opened: GroundedCitation;
  onSelect: (c: GroundedCitation) => void;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const cited = [...answer.citations, ...answer.misses.map((m) => m.citation)];
  const onPage = cited.filter((c, i) => c.document_hash === opened.document_hash && c.page === opened.page
                                        && cited.findIndex((o) => o.span_id === c.span_id) === i);
  const select = (spanId: string) => {
    const next = onPage.find((c) => c.span_id === spanId);
    if (next) onSelect(next);
  };
  const labelId = `ask-panel-${answer.nct_id}`;
  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <button type="button" aria-label="Close" onClick={onClose} className="absolute inset-0 bg-black/30" />
      <aside role="dialog" aria-modal="true" aria-labelledby={labelId}
             className="relative z-50 h-full w-full max-w-xl overflow-y-auto bg-surface border-l border-border p-4 sm:p-5 flex flex-col gap-3">
        <div className="flex items-start justify-between gap-3">
          <h2 id={labelId} className="text-lg font-semibold">{STANDING[answer.standing]}</h2>
          <button type="button" onClick={onClose}
                  className="min-h-11 rounded-lg border border-border px-4 text-sm font-semibold">Close</button>
        </div>
        <p className="text-sm text-muted">You asked: {answer.question}</p>
        <blockquote className="border-l-4 border-accent pl-3">“{opened.quote}”</blockquote>
        <RegionPage documentHash={opened.document_hash} page={opened.page} filename={opened.filename}
                    boxes={onPage} active={opened.span_id} onSelect={select} />
      </aside>
    </div>
  );
}
