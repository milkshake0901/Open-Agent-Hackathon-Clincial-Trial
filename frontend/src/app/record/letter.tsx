"use client";

import { useEffect, useState } from "react";
import { api, type AskAnswer } from "@/lib/api";

const DEFAULT_QUESTION = "Has this patient had chemotherapy in the last ten days?";
// The model call is the long part, usually under a minute. The bar approaches 90% on that clock,
// then finishes when the cited page has been drawn.
const READ_MS = 45_000;

const ANSWER: Record<AskAnswer["answer"], string> = {
  yes: "Yes",
  no: "No",
  unknown: "Not in the letter",
};

function asOf(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

function readingFraction(elapsedMs: number): number {
  return Math.min(0.9, 0.08 + (elapsedMs / READ_MS) * 0.82);
}

export function LetterQuestion({ patientId }: { patientId: string }) {
  const [question, setQuestion] = useState(DEFAULT_QUESTION);
  const [answer, setAnswer] = useState<AskAnswer | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [highlighting, setHighlighting] = useState(false);
  const [pagesLeft, setPagesLeft] = useState(0);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!pending) return;
    const started = performance.now();
    const id = window.setInterval(() => setElapsedMs(performance.now() - started), 200);
    return () => window.clearInterval(id);
  }, [pending]);

  useEffect(() => {
    if (highlighting && pagesLeft <= 0) setHighlighting(false);
  }, [highlighting, pagesLeft]);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setPending(true);
    setHighlighting(false);
    setElapsedMs(0);
    setAnswer(null);
    setError(null);
    try {
      const next = await api.ask(patientId, question);
      const cited = new Set(next.citations.map((c) => c.page));
      setAnswer(next);
      setActive(next.citations[0]?.span_id ?? null);
      setPagesLeft(cited.size || 1);
      setHighlighting(true);
    } catch (err) {
      setAnswer(null);
      setError((err as Error).message);
    } finally {
      setPending(false);
    }
  }

  function onPageDrawn() {
    setPagesLeft((left) => Math.max(0, left - 1));
  }

  const showBar = pending || highlighting;
  const fraction = pending ? readingFraction(elapsedMs) : 1;
  const seconds = Math.floor(elapsedMs / 1000);
  const barLabel = pending ? `Reading the letter, ${seconds}s` : "Placing the highlight";

  const citedPages = answer
    ? [...new Set(answer.citations.map((c) => c.page))].sort((a, b) => a - b)
    : [];
  const pages = citedPages.length ? citedPages : answer ? [1] : [];

  return (
    <div className="flex flex-col gap-6">
      <form onSubmit={onSubmit} className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <label className="flex min-w-0 flex-1 flex-col gap-1 text-sm">
          Question
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            disabled={pending}
            className="rounded-md border border-border bg-surface px-3 py-2 text-base"
          />
        </label>
        <button
          type="submit"
          disabled={pending || !question.trim()}
          className="rounded-md bg-accent px-4 py-2 text-white disabled:opacity-50"
        >
          {pending ? "Reading the letter…" : "Ask"}
        </button>
      </form>

      {showBar && (
        <div className="flex flex-col gap-2">
          <div
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(fraction * 100)}
            aria-valuetext={barLabel}
            className="h-1.5 overflow-hidden rounded-full bg-border"
          >
            <div
              className="h-full rounded-full bg-accent transition-[width] duration-200 ease-linear"
              style={{ width: `${fraction * 100}%` }}
            />
          </div>
          <p className="text-sm text-muted">{barLabel}</p>
        </div>
      )}

      {error && (
        <p role="alert" className="text-sm">
          {error}
        </p>
      )}

      {answer && (
        <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
          <section className="flex flex-col gap-4">
            <p className="text-5xl font-semibold tracking-tight">{ANSWER[answer.answer]}</p>
            <p className="text-sm text-muted">
              Ten days means the ten days up to {asOf(answer.as_of)}, including that day. {answer.patient_label}.{" "}
              {answer.filename}.
            </p>
            <p>{answer.reasoning}</p>
            {answer.citations.length === 0 ? (
              <p className="text-sm text-muted">The model did not point at a region of the letter.</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {answer.citations.map((c) => {
                  const on = c.span_id === active;
                  return (
                    <li key={c.span_id}>
                      <button
                        type="button"
                        onClick={() => setActive(c.span_id)}
                        aria-pressed={on}
                        className={`w-full rounded-md border px-3 py-2 text-left text-sm ${
                          on ? "border-accent" : "border-border"
                        }`}
                      >
                        <span className="text-muted">Page {c.page}</span>
                        <span className="mt-1 block">{c.quote}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          <section className="flex flex-col gap-4">
            <h2 className="text-sm text-muted">Where the letter says it</h2>
            {pages.map((page) => {
              const boxes = answer.citations.filter((c) => c.page === page);
              return (
                <figure key={page} className="flex flex-col gap-2">
                  <div className="relative border border-border bg-surface">
                    {/* The image is the parsed page. A box is a fraction of that page, origin at the top left. */}
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={`/api/documents/${encodeURIComponent(answer.document_hash)}/pages/${page}/image`}
                      alt={`Page ${page} of ${answer.filename}`}
                      className="block w-full"
                      onLoad={onPageDrawn}
                      onError={onPageDrawn}
                    />
                    {boxes.map((c) => (
                      <button
                        key={c.span_id}
                        type="button"
                        aria-label={`Cited region on page ${page}`}
                        onClick={() => setActive(c.span_id)}
                        className={`absolute border-2 border-accent ${
                          c.span_id === active ? "bg-accent/25" : "bg-accent/10"
                        }`}
                        style={{
                          left: `${c.x0 * 100}%`,
                          top: `${c.y0 * 100}%`,
                          width: `${(c.x1 - c.x0) * 100}%`,
                          height: `${(c.y1 - c.y0) * 100}%`,
                        }}
                      />
                    ))}
                  </div>
                  <figcaption className="text-sm text-muted">
                    Page {page} of {answer.page_count}
                  </figcaption>
                </figure>
              );
            })}
          </section>
        </div>
      )}
    </div>
  );
}
