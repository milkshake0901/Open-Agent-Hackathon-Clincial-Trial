"use client";

// Flow step 1 (optional): start from a referral letter. The PDF is added to the Respondent's own record and read in
// the background, page by page into Regions, then into drafted Facts that wait for Letter review. The questionnaire
// can be answered meanwhile; it skips what the letter answers once the letter is read.

import { useEffect, useState } from "react";
import { api, type IntakeStatus, type SavedReferral } from "@/lib/api";

export type LetterChoice = { kind: "letter"; runId: string; filename: string } | { kind: "none" };

export function LetterStart({ ensurePatient, onChosen, onUseSaved }: {
  ensurePatient: () => Promise<string>;
  onChosen: (choice: LetterChoice) => void;
  onUseSaved: (saved: SavedReferral) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [pending, setPending] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<SavedReferral | null>(null);

  useEffect(() => {
    if (!pending) return;
    const started = Date.now();
    const id = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(id);
  }, [pending]);

  useEffect(() => {
    api.savedReferral().then(setSaved).catch(() => setSaved(null));
  }, []);

  async function add() {
    if (!file) return;
    setPending(true);
    setError(null);
    try {
      const patientId = await ensurePatient();
      const accepted = await api.addDocument(patientId, file);
      onChosen({ kind: "letter", runId: accepted.run_id, filename: file.name });
    } catch (err) {
      setError((err as Error).message);
      setPending(false);
    }
  }

  const button = "min-h-12 rounded-lg px-5 text-base font-semibold disabled:opacity-60";
  return (
    <section aria-labelledby="letter-start" className="rounded-xl border border-border bg-surface p-5 flex flex-col gap-4">
      <h2 id="letter-start" className="text-lg font-semibold">Start from a referral letter</h2>
      <p className="text-muted">
        If you have a letter or report from a doctor, add it first. We read it in the background while you answer a
        few questions, and skip the ones it answers. Names, addresses and record numbers are removed before anything
        reads it. This step is optional.
      </p>
      <label htmlFor="referral-file" className="font-medium">Choose a PDF letter or report</label>
      <input id="referral-file" type="file" accept="application/pdf,.pdf" disabled={pending}
             onChange={(e) => setFile(e.target.files?.[0] ?? null)}
             className="min-h-12 w-full rounded-lg border border-border px-3 py-2 text-base" />
      <div className="flex flex-wrap gap-3">
        {saved?.version_id && (
          <button type="button" disabled={pending} onClick={() => onUseSaved(saved)}
                  className={`${button} bg-accent text-white dark:text-black`}>
            Use the saved referral
          </button>
        )}
        <button type="button" disabled={!file || pending} onClick={add}
                className={`${button} ${saved?.version_id ? "border border-border" : "bg-accent text-white dark:text-black"}`}>
          {pending ? "Adding the letter…" : "Add this letter"}
        </button>
        <button type="button" disabled={pending} onClick={() => onChosen({ kind: "none" })}
                className={`${button} border border-border`}>
          I don&apos;t have a letter
        </button>
      </div>
      {saved && (
        <p className="text-muted">
          {saved.filename} is already read. Using it skips sending the PDF again.
        </p>
      )}
      {pending && (
        <div className="flex flex-col gap-2" role="status" aria-live="polite">
          <p>Reading the PDF… {clock(elapsed)}</p>
          <div className="h-2 overflow-hidden rounded-full bg-border" role="progressbar" aria-label="Reading the PDF">
            <div className="h-full w-1/4 rounded-full bg-accent" style={{ animation: "letter-slide 1.4s ease-in-out infinite" }} />
          </div>
        </div>
      )}
      <div role="status" aria-live="polite">
        {error && <p role="alert" className="text-red-700 dark:text-red-400">{error}</p>}
      </div>
    </section>
  );
}

const clock = (seconds: number) => {
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return minutes > 0 ? `${minutes}m ${rest}s` : `${rest}s`;
};

const DONE = new Set(["awaiting_review", "awaiting_patient", "committed"]);

// Where the letter stands, above the questionnaire: a bar while its pages are read, then a button that fills the form.
export function LetterProgress({ filename, phase, pages, pagesRead, details, onFill }: {
  filename: string;
  phase: IntakeStatus["letters"][number]["phase"] | null;
  pages: number;
  pagesRead: number;
  details: Record<string, string>;
  onFill?: (details: Record<string, string>) => void;
}) {
  const [seconds, setSeconds] = useState(0);
  const done = phase !== null && DONE.has(phase);
  const failed = phase === "rejected";
  useEffect(() => {
    if (done || failed) return;
    const started = Date.now();
    const id = window.setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(id);
  }, [done, failed]);

  const known = pages > 0 && pagesRead > 0;
  const pct = done ? 100 : known ? Math.min(100, Math.round((pagesRead / pages) * 100)) : null;
  const took = seconds > 0 ? ` in ${clock(seconds)}` : "";
  const text = failed
    ? "We could not read facts from it. Please answer the questions instead."
    : phase === "awaiting_patient"
      ? `Read${took}. Something in it differs from what we have; please tell us which is right below.`
      : done
        ? `Read${took}.`
        : known
          ? `Extracting the details, page ${pagesRead} of ${pages} · ${clock(seconds)}`
          : `Reading the letter… ${clock(seconds)}`;
  const canFill = done && onFill && Object.keys(details).length > 0;

  return (
    <div className="rounded-lg border border-border p-3 flex flex-col gap-3" role="status" aria-live="polite">
      <p><span className="font-medium break-all">{filename}</span>: {text}</p>
      {!failed && !done && (
        <div className="h-2 overflow-hidden rounded-full bg-border" role="progressbar"
             aria-label="Extracting the letter" aria-valuemin={0} aria-valuemax={100}
             aria-valuenow={pct ?? undefined}>
          {pct === null
            ? <div className="h-full w-1/4 rounded-full bg-accent" style={{ animation: "letter-slide 1.4s ease-in-out infinite" }} />
            : <div className="h-full rounded-full bg-accent transition-[width] duration-500" style={{ width: `${pct}%` }} />}
        </div>
      )}
      {canFill && (
        <button type="button" onClick={() => onFill(details)}
                className="min-h-12 self-start rounded-lg bg-accent px-5 text-base font-semibold text-white dark:text-black">
          Use the details from the letter
        </button>
      )}
    </div>
  );
}
