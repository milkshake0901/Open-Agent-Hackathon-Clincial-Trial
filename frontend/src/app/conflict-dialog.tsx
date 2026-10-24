"use client";

// The Conflict dialog: a new Document says something the record already says differently. Both sides are shown
// with their source and page; the Respondent picks which is right for each Conflict, and the answer is committed
// as the next Profile version.

import { useEffect, useRef, useState } from "react";
import { api, type ConflictOut, type ConflictSide, type IngestOutcome, type Resolution } from "@/lib/api";

const CHOICES: { value: Resolution["choice"]; label: (c: ConflictOut) => string }[] = [
  { value: "accept_draft", label: (c) => `${c.draft.filename} is right` },
  {
    value: "keep_accepted",
    label: (c) =>
      c.accepted?.label.startsWith("Patient-reported") ? "My earlier answer is right" : "The earlier document is right",
  },
  { value: "discard_both", label: () => "Neither is right" },
];

function Side({ title, side }: { title: string; side: ConflictSide }) {
  return (
    <div className="flex-1 rounded-lg border border-border p-3 flex flex-col gap-2 min-w-0">
      <p className="text-sm font-semibold uppercase tracking-wide text-muted">{title}</p>
      <p className="text-lg font-semibold break-words">&ldquo;{side.quote}&rdquo;</p>
      <p className="text-sm text-muted">
        {side.label}
        {side.observed_on ? `, ${side.observed_on}` : ""}
      </p>
      <details>
        <summary className="cursor-pointer text-sm underline">Show the page</summary>
        <pre className="mt-2 whitespace-pre-wrap break-words text-sm font-sans">{side.page_text}</pre>
      </details>
    </div>
  );
}

export function ConflictDialog({ runId, onDone }: { runId: string; onDone: (outcome: IngestOutcome) => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [conflicts, setConflicts] = useState<ConflictOut[] | null>(null);
  const [choices, setChoices] = useState<Record<string, Resolution["choice"]>>({});
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    api.conflicts(runId).then((r) => setConflicts(r.conflicts), (e: Error) => setError(e.message));
  }, [runId]);

  useEffect(() => {
    if (conflicts?.length && !ref.current?.open) ref.current?.showModal();
  }, [conflicts]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!conflicts) return;
    setSending(true);
    setError(null);
    try {
      const outcome = await api.confirm(
        runId,
        conflicts.filter((c) => choices[c.id]).map((c) => ({ conflict_id: c.id, choice: choices[c.id] })),
      );
      ref.current?.close();
      onDone(outcome);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSending(false);
    }
  }

  const ready = conflicts !== null && conflicts.every((c) => choices[c.id]);

  return (
    <dialog ref={ref} aria-labelledby={`conflict-${runId}`}
            className="m-auto w-[min(48rem,calc(100vw-2rem))] max-h-[calc(100vh-2rem)] rounded-xl border border-border bg-surface p-5 text-[inherit] backdrop:bg-black/50">
      <form onSubmit={onSubmit} className="flex flex-col gap-5">
        <h2 id={`conflict-${runId}`} className="text-lg font-semibold">Which is right?</h2>
        <p className="text-muted">
          A document you added says something different from what we already have. Choose which is right, and we
          will update your record.
        </p>
        {conflicts?.map((c) => (
          <fieldset key={c.id} className="flex flex-col gap-3">
            <legend className="sr-only">{c.message}</legend>
            <div className="flex flex-col gap-3 sm:flex-row">
              <Side title="The new document says" side={c.draft} />
              {c.accepted && <Side title="We already have" side={c.accepted} />}
            </div>
            <div className="flex flex-col gap-2">
              {CHOICES.map((choice) => (
                <label key={choice.value} className="flex min-h-12 items-center gap-3 rounded-lg border border-border px-3">
                  <input type="radio" name={c.id} value={choice.value} checked={choices[c.id] === choice.value}
                         onChange={() => setChoices((s) => ({ ...s, [c.id]: choice.value }))} className="h-5 w-5" />
                  {choice.label(c)}
                </label>
              ))}
            </div>
          </fieldset>
        ))}
        {error && <p role="alert" className="text-red-700 dark:text-red-400">{error}</p>}
        <button type="submit" disabled={!ready || sending}
                className="min-h-12 rounded-lg bg-accent px-5 text-base font-semibold text-white dark:text-black disabled:opacity-60">
          {sending ? "Saving…" : "Save my answer"}
        </button>
      </form>
    </dialog>
  );
}
