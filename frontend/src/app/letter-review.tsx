"use client";

// Letter review: the Facts read from a letter wait, uncommitted, until the Respondent checks them or uses them all as
// read. Each Fact is a plain sentence beside its page with the Region it was read from boxed; flagged ones (a date
// that reads two ways, or one worked out from "4 months ago") come first. "Not right" drops a Fact for good, and what
// it should say becomes one of the Respondent's own answers. The letter's date can be corrected here too.

import { useEffect, useState } from "react";
import { api, type IngestOutcome, type LetterReview as Review, type ReviewFact } from "@/lib/api";
import { RegionPage } from "@/app/region-page";

const longDate = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-AU", { day: "numeric", month: "long", year: "numeric" });

function sentence(f: ReviewFact): string {
  const what = `${f.subject.charAt(0).toUpperCase()}${f.subject.slice(1)}: ${f.value}${f.unit ? ` ${f.unit}` : ""}`;
  if (!f.observed_on) return what;
  const when = longDate(f.observed_on);
  if (f.flags.includes("estimated_date")) return `${what}, about ${when}`;
  if (f.flags.includes("document_date")) return `${what}, as of the letter's date (${when})`;
  return `${what}, on ${when}`;
}

function flagNote(f: ReviewFact): string | null {
  if (f.flags.includes("estimated_date")) return "Please check the date: we worked it out from the letter's wording.";
  if (f.flags.includes("ambiguous_date")) return "Please check the date: the letter's date could be read two ways.";
  return null;
}

export function LetterReview({ runId, onDone }: { runId: string; onDone: (outcome: IngestOutcome) => void }) {
  const [review, setReview] = useState<Review | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [editingDate, setEditingDate] = useState(false);
  const [date, setDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.review(runId).then((r) => {
      setReview(r);
      setSelected(r.facts[0]?.index ?? null);
    }, (e: Error) => setError(e.message));
  }, [runId]);

  async function send<T>(call: () => Promise<T>, then: (value: T) => void) {
    setBusy(true);
    setError(null);
    try {
      then(await call());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!review) {
    return error ? <p role="alert" className="text-red-700 dark:text-red-400">{error}</p>
      : <p className="text-muted" role="status">Loading what we read from your letter…</p>;
  }

  const answer = (f: ReviewFact, decision: "keep" | "drop", correction?: string) =>
    send(() => api.answerReview(runId, f.index, decision, correction), setReview);
  const shown = review.facts.find((f) => f.index === selected) ?? null;
  const checkedCount = review.facts.filter((f) => f.decision).length;

  // On big screens the review is wider than the page column, so the letter is big enough to read.
  return (
    <section aria-labelledby={`review-${runId}`}
             className="rounded-xl border border-border bg-surface p-5 flex flex-col gap-4 md:relative md:left-1/2 md:w-[min(72rem,calc(100vw-2rem))] md:-translate-x-1/2">
      <h2 id={`review-${runId}`} className="text-lg font-semibold">Check what we read from {review.filename}</h2>
      <p className="text-muted">
        Each line is something we read from your letter. Compare it with the boxed part of the page. This step is
        optional: you can use everything as read.
      </p>

      <div className="flex flex-wrap items-center gap-3">
        <p>
          Letter date: <span className="font-medium">{review.document_date ? longDate(review.document_date) : "not found"}</span>
          {review.document_date_corrected && <span className="text-muted"> (corrected by you)</span>}
        </p>
        {!editingDate ? (
          <button type="button" onClick={() => { setDate(review.document_date ?? ""); setEditingDate(true); }}
                  className="min-h-11 rounded-lg border border-border px-4 text-sm font-semibold text-accent">
            Change the date
          </button>
        ) : (
          <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => {
            e.preventDefault();
            if (date) send(() => api.correctDocumentDate(runId, date), (r) => { setReview(r); setEditingDate(false); });
          }}>
            <label htmlFor={`date-${runId}`} className="sr-only">Letter date</label>
            <input id={`date-${runId}`} type="date" value={date} onChange={(e) => setDate(e.target.value)}
                   className="min-h-11 rounded-lg border border-border px-3 text-base" />
            <button type="submit" disabled={busy || !date}
                    className="min-h-11 rounded-lg bg-accent px-4 text-sm font-semibold text-white dark:text-black disabled:opacity-60">
              Save date
            </button>
            <button type="button" onClick={() => setEditingDate(false)} className="min-h-11 px-2 text-sm underline">
              Cancel
            </button>
          </form>
        )}
      </div>

      {/* The letter gets the larger share so it can be read beside the lines. */}
      <div className="grid gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <ol className="flex flex-col gap-3 min-w-0">
          {review.facts.map((f) => {
            const note = flagNote(f);
            const active = f.index === selected;
            return (
              <li key={f.index}
                  className={`rounded-lg border p-3 flex flex-col gap-2 ${active ? "border-accent" : "border-border"}`}>
                <button type="button" onClick={() => setSelected(f.index)} aria-pressed={active}
                        className="text-left font-medium break-words">
                  {sentence(f)}
                </button>
                {note && <p className="text-sm font-medium text-amber-800 dark:text-amber-300">{note}</p>}
                <p className="text-sm text-muted break-words">Page {f.page}: “{f.quote}”</p>
                <div className="flex flex-wrap gap-2" role="group" aria-label={`Is "${sentence(f)}" right?`}>
                  <button type="button" disabled={busy} aria-pressed={f.decision === "keep"}
                          onClick={() => answer(f, "keep")}
                          className={`min-h-11 rounded-lg border px-4 text-sm font-semibold ${f.decision === "keep" ? "border-accent bg-accent text-white dark:text-black" : "border-border"}`}>
                    Looks right
                  </button>
                  <button type="button" disabled={busy} aria-pressed={f.decision === "drop"}
                          onClick={() => { setSelected(f.index); answer(f, "drop", f.correction ?? undefined); }}
                          className={`min-h-11 rounded-lg border px-4 text-sm font-semibold ${f.decision === "drop" ? "border-red-700 bg-red-700 text-white" : "border-border"}`}>
                    Not right
                  </button>
                </div>
                {f.decision === "drop" && (
                  <form className="flex flex-col gap-2" onSubmit={(e) => {
                    e.preventDefault();
                    answer(f, "drop", drafts[f.index] ?? f.correction ?? "");
                  }}>
                    <label htmlFor={`fix-${runId}-${f.index}`} className="text-sm font-medium">
                      What should it say? (optional)
                    </label>
                    <textarea id={`fix-${runId}-${f.index}`} rows={2} maxLength={500}
                              value={drafts[f.index] ?? f.correction ?? ""}
                              onChange={(e) => setDrafts((d) => ({ ...d, [f.index]: e.target.value }))}
                              className="w-full rounded-lg border border-border px-3 py-2 text-base" />
                    <button type="submit" disabled={busy}
                            className="min-h-11 self-start rounded-lg border border-border px-4 text-sm font-semibold text-accent">
                      Save what it should say
                    </button>
                    {f.correction && <p className="text-sm text-muted">Saved. It will be kept as your own answer.</p>}
                  </form>
                )}
              </li>
            );
          })}
        </ol>
        <div className="min-w-0 md:sticky md:top-4 self-start">
          {shown && shown.region ? (
            <RegionPage documentHash={review.document_hash} page={shown.page} filename={review.filename}
                        boxes={[shown.region]} active={shown.region.span_id} />
          ) : (
            <p className="text-muted">Choose a line to see where the letter says it.</p>
          )}
        </div>
      </div>

      {error && <p role="alert" className="text-red-700 dark:text-red-400">{error}</p>}
      <p className="text-sm text-muted">
        {checkedCount} of {review.facts.length} checked. Lines you do not check are saved as read, marked not checked.
      </p>
      <div className="flex flex-wrap gap-3">
        <button type="button" disabled={busy} onClick={() => send(() => api.commitReview(runId), onDone)}
                className="min-h-12 rounded-lg bg-accent px-5 text-base font-semibold text-white dark:text-black disabled:opacity-60">
          Save my checks
        </button>
        <button type="button" disabled={busy} onClick={() => send(() => api.useAllAsRead(runId), onDone)}
                className="min-h-12 rounded-lg border border-border px-5 text-base font-semibold disabled:opacity-60">
          Use all as read
        </button>
      </div>
    </section>
  );
}
