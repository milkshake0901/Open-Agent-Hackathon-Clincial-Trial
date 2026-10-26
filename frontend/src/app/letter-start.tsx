"use client";

// Flow step 1 (optional): start from a referral letter. The PDF is added to the Respondent's own record and read in
// the background, page by page into Regions, then into drafted Facts that wait for Letter review. The questionnaire
// can be answered meanwhile; it skips what the letter answers once the letter is read.

import { useState } from "react";
import { api, type IntakeStatus } from "@/lib/api";

export type LetterChoice = { kind: "letter"; runId: string; filename: string } | { kind: "none" };

export function LetterStart({ ensurePatient, onChosen }: {
  ensurePatient: () => Promise<string>;
  onChosen: (choice: LetterChoice) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
        <button type="button" disabled={!file || pending} onClick={add}
                className={`${button} bg-accent text-white dark:text-black`}>
          {pending ? "Adding the letter…" : "Add this letter"}
        </button>
        <button type="button" disabled={pending} onClick={() => onChosen({ kind: "none" })}
                className={`${button} border border-border`}>
          I don&apos;t have a letter
        </button>
      </div>
      <div role="status" aria-live="polite">
        {error && <p role="alert" className="text-red-700 dark:text-red-400">{error}</p>}
      </div>
    </section>
  );
}

// One line on where the letter stands, shown above the questionnaire and the later steps.
export function LetterProgress({ filename, phase }: { filename: string; phase: IntakeStatus["letters"][number]["phase"] | null }) {
  const text = phase === null || phase === "started" || phase === "drafting"
    ? "Reading it in the background. You can answer the questions below meanwhile."
    : phase === "awaiting_review"
      ? "Read. You can check what we read from it after saving your answers."
      : phase === "awaiting_patient"
        ? "Read. Something in it differs from what we have; please tell us which is right below."
        : phase === "committed"
          ? "Read and added to your record."
          : "We could not read facts from it. Please answer the questions instead.";
  return (
    <p role="status" aria-live="polite" className="rounded-lg border border-border p-3">
      <span className="font-medium break-all">{filename}</span>: {text}
    </p>
  );
}
