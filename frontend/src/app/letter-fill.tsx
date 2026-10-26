"use client";

import { useEffect, useState } from "react";
import { api, type LetterOut } from "@/lib/api";

const FILLED: Record<string, string> = {
  respondent: "who is answering",
  sex: "sex",
  diagnosis: "diagnosis",
  diagnosis_when: "when diagnosed",
  treatments: "treatments",
  medicines: "medicines now",
};

export function LetterFill({ onFill }: { onFill: (letter: LetterOut) => void }) {
  const [letters, setLetters] = useState<LetterOut[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filled, setFilled] = useState<string | null>(null);

  useEffect(() => {
    api.referralLetters().then((r) => setLetters(r.letters)).catch(() => setLetters([]));
  }, []);

  async function apply(run: () => Promise<LetterOut>, waiting: string) {
    setPending(waiting);
    setError(null);
    setFilled(null);
    try {
      const letter = await run();
      onFill(letter);
      const names = Object.keys(letter.answers).map((id) => FILLED[id] ?? id);
      setFilled(`Filled ${names.join(", ")} from ${letter.filename}. Check them before saving.`);
      setLetters((now) => now.some((one) => one.document_hash === letter.document_hash) ? now : [letter, ...now]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending(null);
    }
  }

  return (
    <section aria-labelledby="letter-fill" className="rounded-xl border border-border bg-surface p-5 flex flex-col gap-4">
      <h2 id="letter-fill" className="text-lg font-semibold">Start from a referral letter</h2>
      <p className="text-muted">
        Load a PDF referral. A button reads the extracted text and fills the diagnosis, the date, the treatments
        and the current medicines. Anything the letter does not say is left blank.
      </p>
      <label htmlFor="referral-file" className="font-medium">Choose a referral letter</label>
      <input id="referral-file" type="file" accept="application/pdf,.pdf" disabled={pending !== null}
             onChange={(e) => setFile(e.target.files?.[0] ?? null)}
             className="min-h-12 w-full rounded-lg border border-border px-3 py-2 text-base" />
      <button type="button" disabled={!file || pending !== null}
              onClick={() => file && apply(() => api.loadReferral(file), "Reading the letter…")}
              className="min-h-12 self-start rounded-lg bg-accent px-5 text-base font-semibold text-white dark:text-black disabled:opacity-60">
        {pending === "Reading the letter…" ? "Reading the letter…" : "Fill answers from this letter"}
      </button>
      {letters.length > 0 && (
        <div className="flex flex-col gap-2">
          <p className="font-medium">Already read</p>
          {letters.map((letter) => (
            <button key={letter.document_hash} type="button" disabled={pending !== null}
                    onClick={() => apply(() => api.prefillReferral(letter.patient_id), letter.filename)}
                    className="min-h-12 self-start rounded-lg border border-border px-5 text-base font-semibold disabled:opacity-60">
              {pending === letter.filename ? "Filling answers…" : `Fill from ${letter.filename}`}
            </button>
          ))}
        </div>
      )}
      <div role="status" aria-live="polite">
        {pending && <p className="text-muted">{pending === "Reading the letter…" ? "Reading the letter. This usually takes under a minute." : "Filling the form from the extracted text…"}</p>}
        {filled && <p>{filled}</p>}
        {error && <p role="alert" className="text-red-700 dark:text-red-400">{error}</p>}
      </div>
    </section>
  );
}
