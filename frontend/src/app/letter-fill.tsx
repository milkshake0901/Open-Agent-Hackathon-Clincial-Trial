"use client";

import { useState } from "react";
import { api, type LetterOut } from "@/lib/api";

const FILLED: Record<string, string> = {
  respondent: "who is answering",
  sex: "sex",
  diagnosis: "diagnosis",
  diagnosis_when: "when diagnosed",
  treatments: "treatments",
  medicines: "medicines now",
};

// The letter is added to the Respondent's own record, like any Document: it is read into Regions and the Intake agent
// drafts its Facts in the background (each citing the Region it quotes). Until the short questionnaire lands (#49),
// the answers are still filled from the letter's Regions too.
export function LetterFill({ ensurePatient, onFill }: {
  ensurePatient: () => Promise<string>;
  onFill: (letter: LetterOut) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filled, setFilled] = useState<string | null>(null);

  async function read() {
    if (!file) return;
    setPending(true);
    setError(null);
    setFilled(null);
    try {
      const patientId = await ensurePatient();
      await api.addDocument(patientId, file);
      const letter = await api.prefillReferral(patientId);
      onFill(letter);
      const names = Object.keys(letter.answers).map((id) => FILLED[id] ?? id);
      setFilled(names.length
        ? `Filled ${names.join(", ")} from ${letter.filename}. Check them before saving.`
        : `Added ${letter.filename} to your record.`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-labelledby="letter-fill" className="rounded-xl border border-border bg-surface p-5 flex flex-col gap-4">
      <h2 id="letter-fill" className="text-lg font-semibold">Start from a referral letter</h2>
      <p className="text-muted">
        Add a PDF referral to your record. It is read page by page, and each trial reason can then show the place in
        the letter it came from. The diagnosis, the date, the treatments and the current medicines are filled in from
        it; anything the letter does not say is left blank.
      </p>
      <label htmlFor="referral-file" className="font-medium">Choose a referral letter</label>
      <input id="referral-file" type="file" accept="application/pdf,.pdf" disabled={pending}
             onChange={(e) => setFile(e.target.files?.[0] ?? null)}
             className="min-h-12 w-full rounded-lg border border-border px-3 py-2 text-base" />
      <button type="button" disabled={!file || pending} onClick={read}
              className="min-h-12 self-start rounded-lg bg-accent px-5 text-base font-semibold text-white dark:text-black disabled:opacity-60">
        {pending ? "Reading the letter…" : "Add this letter and fill answers"}
      </button>
      <div role="status" aria-live="polite">
        {pending && <p className="text-muted">Reading the letter. This usually takes under a minute.</p>}
        {filled && <p>{filled}</p>}
        {error && <p role="alert" className="text-red-700 dark:text-red-400">{error}</p>}
      </div>
    </section>
  );
}
