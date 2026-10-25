"use client";

// Flow step 4: the Diagnosis check (ADR 0005). The backend offers a shortlist of Condition labels that stored Trials
// use, each with how many open and past trials list it. The Respondent ticks the ones that match (they become the
// Condition term Trials are selected by), answers none of these (and can re-word, which starts a new check), or not
// sure, which points to the GP.

import { useEffect, useState } from "react";
import { api, type DiagnosisAnswer, type DiagnosisCheck } from "@/lib/api";

const trialCount = (n: number, kind: string) => `${n} ${kind} trial${n === 1 ? "" : "s"}`;

export function DiagnosisCheckCard({ patientId }: { patientId: string }) {
  const [check, setCheck] = useState<DiagnosisCheck | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [ticked, setTicked] = useState<string[]>([]);
  const [noneOfThese, setNoneOfThese] = useState(false);
  const [rewording, setRewording] = useState("");

  async function run(step: () => Promise<DiagnosisCheck>) {
    setBusy(true);
    setError(null);
    try {
      setCheck(await step());
      setTicked([]);
      setNoneOfThese(false);
      setRewording("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const answer = (a: DiagnosisAnswer) => check && run(() => api.answerDiagnosis(patientId, check.id, a));

  useEffect(() => {
    api
      .checkDiagnosis(patientId)
      .then(setCheck)
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  }, [patientId]);

  const toggle = (label: string) =>
    setTicked((now) => (now.includes(label) ? now.filter((l) => l !== label) : [...now, label]));

  const button = "min-h-12 rounded-lg border border-border px-5 text-base font-semibold disabled:opacity-60";
  const proposed = check?.status === "proposed";
  // Re-wording is offered after "none of these", and straight away when no label fits.
  const reword = check?.ask_again || (proposed && (noneOfThese || check.shortlist.length === 0));
  return (
    <section aria-labelledby="diagnosis-heading" aria-live="polite"
             className="rounded-xl border border-border bg-surface p-5 flex flex-col gap-3">
      <h2 id="diagnosis-heading" className="text-lg font-semibold">Checking the diagnosis</h2>
      {busy && !check && <p className="text-muted">Reading the diagnosis you gave…</p>}
      {error && <p role="alert" className="text-red-700 dark:text-red-400">{error}</p>}
      {check && <p>{check.message}</p>}
      {proposed && check.shortlist.length > 0 && (
        <fieldset className="flex flex-col gap-2" disabled={busy}>
          <legend className="sr-only">Conditions that match the diagnosis</legend>
          {check.shortlist.map((one) => (
            <label key={one.label} className="flex min-h-12 items-center gap-3 rounded-lg border border-border px-3">
              <input type="checkbox" className="size-5" checked={ticked.includes(one.label)}
                     onChange={() => toggle(one.label)} />
              <span className="flex flex-col">
                <span className="font-medium">{one.label}</span>
                <span className="text-sm text-muted">
                  {trialCount(one.open, "open")} · {trialCount(one.closed, "past")}
                </span>
              </span>
            </label>
          ))}
        </fieldset>
      )}
      {proposed && (
        <div className="flex flex-wrap gap-3">
          {check.shortlist.length > 0 && (
            <>
              <button type="button" disabled={busy || ticked.length === 0}
                      className={`${button} bg-accent text-white dark:text-black`}
                      onClick={() => answer({ answer: "ticked", labels: ticked })}>Use these</button>
              <button type="button" disabled={busy} className={button} aria-pressed={noneOfThese}
                      onClick={() => setNoneOfThese(true)}>None of these</button>
            </>
          )}
          <button type="button" disabled={busy} className={button}
                  onClick={() => answer({ answer: "not_sure" })}>Not sure</button>
        </div>
      )}
      {reword && (
        <form className="flex flex-col gap-2" onSubmit={(e) => {
          e.preventDefault();
          const text = rewording.trim();
          if (!text) return;
          if (proposed) answer({ answer: "none_of_these", text });
          else run(() => api.checkDiagnosis(patientId, text));
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
