"use client";

// Flow step 4: "We understood this as …, is that right?" The backend proposes a condition term for the free-text
// diagnosis; yes makes it the condition Trials are selected by, no asks for a re-wording, not sure points to the GP.

import { useEffect, useState } from "react";
import { api, type DiagnosisCheck } from "@/lib/api";

export function DiagnosisCheckCard({ patientId }: { patientId: string }) {
  const [check, setCheck] = useState<DiagnosisCheck | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [rewording, setRewording] = useState("");

  async function run(step: () => Promise<DiagnosisCheck>) {
    setBusy(true);
    setError(null);
    try {
      setCheck(await step());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    api
      .checkDiagnosis(patientId)
      .then(setCheck)
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  }, [patientId]);

  const button = "min-h-12 rounded-lg border border-border px-5 text-base font-semibold disabled:opacity-60";
  return (
    <section aria-labelledby="diagnosis-heading" aria-live="polite"
             className="rounded-xl border border-border bg-surface p-5 flex flex-col gap-3">
      <h2 id="diagnosis-heading" className="text-lg font-semibold">Checking the diagnosis</h2>
      {busy && !check && <p className="text-muted">Reading the diagnosis you gave…</p>}
      {error && <p role="alert" className="text-red-700 dark:text-red-400">{error}</p>}
      {check && <p>{check.message}</p>}
      {check?.status === "proposed" && (
        <div className="flex flex-wrap gap-3">
          <button type="button" disabled={busy} className={`${button} bg-accent text-white dark:text-black`}
                  onClick={() => run(() => api.answerDiagnosis(patientId, check.id, "yes"))}>Yes</button>
          <button type="button" disabled={busy} className={button}
                  onClick={() => run(() => api.answerDiagnosis(patientId, check.id, "no"))}>No, let me re-word</button>
          <button type="button" disabled={busy} className={button}
                  onClick={() => run(() => api.answerDiagnosis(patientId, check.id, "not_sure"))}>Not sure</button>
        </div>
      )}
      {check?.ask_again && (
        <form className="flex flex-col gap-2" onSubmit={(e) => {
          e.preventDefault();
          if (rewording.trim()) run(() => api.checkDiagnosis(patientId, rewording.trim()));
        }}>
          <label htmlFor="diagnosis-reword" className="font-medium">The diagnosis, in other words</label>
          <textarea id="diagnosis-reword" rows={2} value={rewording} onChange={(e) => setRewording(e.target.value)}
                    className="min-h-12 w-full rounded-lg border border-border bg-transparent px-3 py-2 text-base" />
          <button type="submit" disabled={busy || !rewording.trim()} className={`${button} self-start`}>Check again</button>
        </form>
      )}
    </section>
  );
}
