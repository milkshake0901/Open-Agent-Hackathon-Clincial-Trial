"use client";

// Optional clinical Documents (letters, reports) added after the questionnaire. Every file becomes its own Document and Profile
// version on the server; however many are added at once, this shows one "Checking N documents" state, then
// one line per file. A letter's Facts then wait for Letter review before they are saved.

import { useState } from "react";
import { api, followRun, type IngestOutcome } from "@/lib/api";
import { ConflictDialog } from "./conflict-dialog";
import { LetterReview } from "./letter-review";

type Result =
  | { kind: "added"; version: number; already: boolean; corrections?: "saving" | "saved" | "failed" }
  | { kind: "needs_answer"; runId: string }
  | { kind: "needs_review"; runId: string }
  | { kind: "failed"; reason: string };

type Batch = { names: string[]; done: number } | null;

async function check(patientId: string, file: File): Promise<Result> {
  try {
    const accepted = await api.addDocument(patientId, file);
    const run = await followRun(accepted.run_id);
    const state = run.state!;
    if (state.phase === "committed" && state.version_number !== null)
      return { kind: "added", version: state.version_number, already: accepted.deduplicated };
    if (state.phase === "awaiting_patient") return { kind: "needs_answer", runId: accepted.run_id };
    if (state.phase === "awaiting_review") return { kind: "needs_review", runId: accepted.run_id };
    return { kind: "failed", reason: state.reason ?? "It could not be checked." };
  } catch (err) {
    return { kind: "failed", reason: (err as Error).message };
  }
}

// What a Conflict's answer or a Letter review's commit leaves the file at.
function settled(o: IngestOutcome, before: Result): Result {
  if (o.outcome === "committed" && o.version_number !== null)
    return { kind: "added", version: o.version_number, already: false,
             corrections: o.correction_run_id ? "saving" : undefined };
  if (o.outcome === "awaiting_review") return { kind: "needs_review", runId: o.run_id };
  if (o.outcome === "rejected") return { kind: "failed", reason: o.reason ?? "It could not be checked." };
  return before;
}

const plural = (n: number) => `${n} document${n === 1 ? "" : "s"}`;

export function AddDocuments({ patientId }: { patientId: string }) {
  const [picked, setPicked] = useState<File[]>([]);
  const [batch, setBatch] = useState<Batch>(null);
  const [results, setResults] = useState<{ name: string; result: Result }[]>([]);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!picked.length || batch) return;
    const files = picked;
    const form = e.currentTarget;
    setBatch({ names: files.map((f) => f.name), done: 0 });
    const checked = await Promise.all(
      files.map(async (f) => {
        const result = await check(patientId, f);
        setBatch((b) => (b ? { ...b, done: b.done + 1 } : b));
        return { name: f.name, result };
      }),
    );
    setResults((r) => [...r, ...checked]);
    setBatch(null);
    setPicked([]);
    form.reset();
  }

  return (
    <section aria-labelledby="documents-heading" className="rounded-xl border border-border bg-surface p-5 flex flex-col gap-4">
      <h2 id="documents-heading" className="text-lg font-semibold">Have letters or reports?</h2>
      <p className="text-muted">
        Adding them makes results more accurate. This step is optional. PDF files only; names, addresses and record
        numbers are removed before anything reads them.
      </p>
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <label htmlFor="documents" className="font-medium">Choose one or more files</label>
        <input id="documents" type="file" multiple accept="application/pdf,.pdf" disabled={batch !== null}
               onChange={(e) => setPicked(Array.from(e.target.files ?? []))}
               className="min-h-12 w-full rounded-lg border border-border px-3 py-2 text-base" />
        <button type="submit" disabled={!picked.length || batch !== null}
                className="min-h-12 rounded-lg bg-accent px-5 text-base font-semibold text-white dark:text-black disabled:opacity-60">
          {picked.length > 1 ? `Add ${plural(picked.length)}` : "Add document"}
        </button>
      </form>
      <div role="status" aria-live="polite">
        {batch && (
          <div className="flex flex-col gap-2">
            <p className="font-medium">Checking {plural(batch.names.length)}…</p>
            <progress value={batch.done} max={batch.names.length} className="w-full accent-[var(--accent)]"
                      aria-label={`${batch.done} of ${plural(batch.names.length)} checked`} />
            <p className="text-sm text-muted">{batch.done} of {batch.names.length} checked</p>
          </div>
        )}
      </div>
      {results.map(({ result }, i) => {
        const update = (o: IngestOutcome) => {
          setResults((rs) => rs.map((r, j) => (j !== i ? r : { ...r, result: settled(o, r.result) })));
          if (o.correction_run_id) {
            followRun(o.correction_run_id).then((run) => setResults((rs) => rs.map((r, j) => {
              if (j !== i || r.result.kind !== "added") return r;
              const st = run.state!;
              return st.phase === "committed" && st.version_number !== null
                ? { ...r, result: { ...r.result, version: st.version_number, corrections: "saved" } }
                : { ...r, result: { ...r.result, corrections: "failed" } };
            })));
          }
        };
        if (result.kind === "needs_answer") return <ConflictDialog key={result.runId} runId={result.runId} onDone={update} />;
        if (result.kind === "needs_review") return <LetterReview key={result.runId} runId={result.runId} onDone={update} />;
        return null;
      })}
      {results.length > 0 && (
        <ul className="flex flex-col gap-2">
          {results.map(({ name, result }, i) => (
            <li key={`${name}-${i}`} className="rounded-lg border border-border p-3">
              <p className="font-medium break-all">{name}</p>
              <p className={result.kind === "failed" ? "text-red-700 dark:text-red-400" : "text-muted"}>
                {result.kind === "added"
                  ? result.already
                    ? `Already added (version ${result.version}).`
                    : `Added. Your record is now version ${result.version}.` + (
                      result.corrections === "saving" ? " Saving your corrections as your own answers…"
                        : result.corrections === "saved" ? " Your corrections are saved as your own answers."
                          : result.corrections === "failed" ? " Your corrections could not be saved." : "")
                  : result.kind === "needs_answer"
                    ? "Something in it differs from what we have. Please tell us which is right."
                    : result.kind === "needs_review"
                      ? "Read. Please check what we read from it below, or use it all as read."
                      : `Not added: ${result.reason}`}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
