"use client";

import { useEffect, useState } from "react";
import { api, type ClosedTrialOut, type GroundedCitation, type MatchingTrials, type TrialAsk } from "@/lib/api";

const ASK_MS = 60_000;
const SUGGESTED = ["Am I eligible?", "What should I gather before applying?"];

const STANDING: Record<TrialAsk["standing"], string> = {
  eligible: "Looks eligible from the letter",
  possible: "Possibly a fit",
  excluded: "The letter appears to rule this out",
  needs_information: "More information is needed",
};

function askFraction(elapsedMs: number): number {
  return Math.min(0.9, 0.08 + (elapsedMs / ASK_MS) * 0.82);
}

function LetterView({ citations, active, onSelect }: {
  citations: GroundedCitation[];
  active: string | null;
  onSelect: (spanId: string) => void;
}) {
  const pages = [...new Set(citations.map((c) => `${c.document_hash}:${c.page}`))];
  return (
    <div className="flex flex-col gap-4">
      {pages.map((key) => {
        const [hash, pageText] = [key.slice(0, key.lastIndexOf(":")), key.slice(key.lastIndexOf(":") + 1)];
        const page = Number(pageText);
        const boxes = citations.filter((c) => c.document_hash === hash && c.page === page);
        const filename = boxes[0]?.filename ?? "letter";
        return (
          <figure key={key} className="flex flex-col gap-2">
            <div className="relative border border-border bg-surface">
              {/* The image is the parsed page. A box is a fraction of that page, origin at the top left. */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={`/api/documents/${encodeURIComponent(hash)}/pages/${page}/image`}
                   alt={`Page ${page} of ${filename}`} className="block w-full" />
              {boxes.map((c) => (
                <button key={c.span_id} type="button" aria-label={`Cited region on page ${page}`}
                        onClick={() => onSelect(c.span_id)}
                        className={`absolute border-2 border-accent ${c.span_id === active ? "bg-accent/25" : "bg-accent/10"}`}
                        style={{
                          left: `${c.x0 * 100}%`, top: `${c.y0 * 100}%`,
                          width: `${(c.x1 - c.x0) * 100}%`, height: `${(c.y1 - c.y0) * 100}%`,
                        }} />
              ))}
            </div>
            <figcaption className="text-sm text-muted">Page {page} of {filename}</figcaption>
          </figure>
        );
      })}
    </div>
  );
}

// The referral is metastatic castration-resistant prostate cancer. These phrases are the names stored
// Australian trials use for that diagnosis, including the short form and the "castrate" spelling.
const PHRASES = [
  "metastatic castration-resistant prostate cancer",
  "metastatic castrate resistant prostate cancer",
  "mCRPC",
];

const statusLabel = (status: string) => status.toLowerCase().replaceAll("_", " ");

function TrialCard({ trial, patientId, askable }: { trial: ClosedTrialOut; patientId: string; askable: boolean }) {
  const [question, setQuestion] = useState(SUGGESTED[0]);
  const [pending, setPending] = useState(false);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [answer, setAnswer] = useState<TrialAsk | null>(null);
  const [shown, setShown] = useState(false);
  const [active, setActive] = useState<string | null>(null);
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
    setShown(false);
    setActive(null);
    setAnswer(null);
    setError(null);
    try {
      const next = await api.askTrial(patientId, trial.nct_id, asked);
      setAnswer(next);
      setActive(next.misses[0]?.citation.span_id ?? next.citations[0]?.span_id ?? null);
    } catch (err) {
      setAnswer(null);
      setError((err as Error).message);
    } finally {
      setPending(false);
    }
  }

  return (
    <article className="rounded-xl border border-border bg-surface p-5 flex flex-col gap-3">
      <header className="flex flex-col gap-1">
        <h3 className="font-semibold">{trial.title}</h3>
        <p className="text-sm text-muted">
          <a href={trial.url} className="underline" rel="noreferrer" target="_blank">{trial.nct_id}</a>
          {" · "}{statusLabel(trial.status)}
        </p>
      </header>
      {askable && (
        <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); void onAsk(question); }}>
          <div className="flex flex-wrap gap-2">
            {SUGGESTED.map((prompt) => (
              <button key={prompt} type="button" disabled={pending} onClick={() => void onAsk(prompt)}
                      className="min-h-10 rounded-lg border border-border px-3 text-sm font-semibold disabled:opacity-60">
                {prompt}
              </button>
            ))}
          </div>
          <label className="flex flex-col gap-1 text-sm">
            Ask about this trial
            <input value={question} onChange={(e) => setQuestion(e.target.value)} disabled={pending}
                   className="rounded-md border border-border bg-transparent px-3 py-2 text-base" />
          </label>
          <button type="submit" disabled={pending || !question.trim()}
                  className="min-h-10 self-start rounded-lg bg-accent px-4 text-sm font-semibold text-white dark:text-black disabled:opacity-60">
            {pending ? "Reading the letter and the criteria…" : "Ask"}
          </button>
          {pending && (
            <div className="flex flex-col gap-2">
              <div role="progressbar" aria-valuemin={0} aria-valuemax={100}
                   aria-valuenow={Math.round(askFraction(elapsedMs) * 100)}
                   aria-valuetext={`Reading the letter and the criteria, ${Math.floor(elapsedMs / 1000)} seconds`}
                   className="h-1.5 overflow-hidden rounded-full bg-border">
                <div className="h-full rounded-full bg-accent transition-[width] duration-200 ease-linear"
                     style={{ width: `${askFraction(elapsedMs) * 100}%` }} />
              </div>
              <p className="text-sm text-muted">Reading the letter and the criteria, {Math.floor(elapsedMs / 1000)}s</p>
            </div>
          )}
          {error && <p role="alert" className="text-sm text-red-700 dark:text-red-400">{error}</p>}
          {answer && (
            <div className="flex flex-col gap-2 text-sm">
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
                  <p className="font-medium">Exclusion criteria the letter shows</p>
                  <ul className="flex flex-col gap-2">
                    {answer.misses.map((miss) => {
                      const on = miss.citation.span_id === active;
                      return (
                        <li key={miss.criterion_id}>
                          <button type="button" aria-pressed={on} onClick={() => { setActive(miss.citation.span_id); setShown(true); }}
                                  className={`w-full rounded-md border px-3 py-2 text-left ${on ? "border-accent" : "border-border"}`}>
                            <span className="block font-medium">{miss.clause}</span>
                            {miss.why && <span className="mt-1 block">{miss.why}</span>}
                            <span className="mt-1 block text-muted">Page {miss.citation.page}: {miss.citation.quote}</span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )}
              {answer.citations.length > 0 && (
                <button type="button" onClick={() => setShown((open) => !open)}
                        className="min-h-10 self-start rounded-lg border border-border px-3 text-sm font-semibold">
                  {shown ? "Hide the letter" : "Show on the letter"}
                </button>
              )}
              {shown && answer.citations.length > 0 && (
                <LetterView citations={answer.citations} active={active} onSelect={setActive} />
              )}
              <p className="text-muted">Read through {answer.via === "zetaris" ? "Zetaris" : "Postgres"}</p>
            </div>
          )}
        </form>
      )}
    </article>
  );
}

export function MatchingTrialsList({ patientId }: { patientId: string }) {
  const [state, setState] = useState<MatchingTrials | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.matchingTrials(PHRASES)
      .then(setState)
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error) return <p role="alert" className="text-red-700 dark:text-red-400">{error}</p>;
  if (!state) return <p className="text-muted">Looking up stored Australian trials…</p>;

  return (
    <div className="flex flex-col gap-8">
      <section aria-labelledby="open-trials" className="flex flex-col gap-3">
        <h2 id="open-trials" className="text-lg font-semibold">Open trials ({state.open.length})</h2>
        <p className="text-muted">
          These are still taking people in Australia. Ask a question to read this trial's criteria and the referral
          through Zetaris, then have the model answer from those words.
        </p>
        {state.open.map((trial) => <TrialCard key={trial.nct_id} trial={trial} patientId={patientId} askable />)}
      </section>
      <details className="flex flex-col gap-3">
        <summary className="cursor-pointer min-h-11 flex items-center text-lg font-semibold">
          Past trials ({state.closed.length})
        </summary>
        <p className="text-muted mt-3">These have stopped taking new people. Newest first.</p>
        <div className="flex flex-col gap-3 mt-3">
          {state.closed.map((trial) => <TrialCard key={trial.nct_id} trial={trial} patientId={patientId} askable={false} />)}
        </div>
      </details>
    </div>
  );
}
