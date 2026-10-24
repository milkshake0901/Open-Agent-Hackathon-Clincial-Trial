"use client";

// Optional clinical Document uploads after the questionnaire. Every file becomes its own Document and Profile
// version on the server; however many are added at once, this shows one "Checking N documents" state, then
// one line per file.

import { useState } from "react";
import { api, followRun } from "@/lib/api";
import { ConflictDialog } from "./conflict-dialog";

type Result =
  | { kind: "added"; version: number; already: boolean }
  | { kind: "needs_answer"; runId: string }
  | { kind: "failed"; reason: string };

type Batch = { files: string[]; done: number } | null;

async function check(patientId: string, file: File): Promise<Result> {
  try {
    const accepted = await api.upload(patientId, file);
    const run = await followRun(accepted.run_id);
    const state = run.state!;
    if (state.phase === "committed" && state.version_number !== null)
      return { kind: "added", version: state.version_number, already: accepted.deduplicated };
    if (state.phase === "awaiting_patient") return { kind: "needs_answer", runId: accepted.run_id };
    return { kind: "failed", reason: state.reason ?? "It could not be checked." };
  } catch (err) {
    return { kind: "failed", reason: (err as Error).message };
  }
}

const plural = (n: number) => `${n} document${n === 1 ? "" : "s"}`;

export function DocumentUploads({ patientId }: { patientId: string }) {
  const [picked, setPicked] = useState<File[]>([]);
  const [batch, setBatch] = useState<Batch>(null);
  const [results, setResults] = useState<{ name: string; result: Result }[]>([]);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!picked.length || batch) return;
    const files = picked;
    const form = e.currentTarget;
    setBatch({ files: files.map((f) => f.name), done: 0 });
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
    <section aria-labelledby="uploads-heading" className="rounded-xl border border-border bg-surface p-5 flex flex-col gap-4">
      <h2 id="uploads-heading" className="text-lg font-semibold">Have letters or reports?</h2>
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
            <p className="font-medium">Checking {plural(batch.files.length)}…</p>
            <progress value={batch.done} max={batch.files.length} className="w-full accent-[var(--accent)]"
                      aria-label={`${batch.done} of ${plural(batch.files.length)} checked`} />
            <p className="text-sm text-muted">{batch.done} of {batch.files.length} checked</p>
          </div>
        )}
      </div>
      {results.map(({ result }, i) =>
        result.kind === "needs_answer" ? (
          <ConflictDialog key={result.runId} runId={result.runId}
                          onDone={(o) => setResults((rs) => rs.map((r, j) => (j !== i ? r : {
                            ...r,
                            result: o.outcome === "committed" && o.version_number !== null
                              ? { kind: "added", version: o.version_number, already: false }
                              : o.outcome === "rejected"
                                ? { kind: "failed", reason: o.reason ?? "It could not be checked." }
                                : r.result,
                          })))} />
        ) : null,
      )}
      {results.length > 0 && (
        <ul className="flex flex-col gap-2">
          {results.map(({ name, result }, i) => (
            <li key={`${name}-${i}`} className="rounded-lg border border-border p-3">
              <p className="font-medium break-all">{name}</p>
              <p className={result.kind === "failed" ? "text-red-700 dark:text-red-400" : "text-muted"}>
                {result.kind === "added"
                  ? result.already
                    ? `Already added (version ${result.version}).`
                    : `Added. Your record is now version ${result.version}.`
                  : result.kind === "needs_answer"
                    ? "Something in it differs from what we have. Please tell us which is right."
                    : `Not added: ${result.reason}`}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
