"use client";

// Questions for you: Respondent questions, each pointing back at one questionnaire question. They are answered
// inline; sending resubmits the whole questionnaire (the latest answers with these changed), which makes a new
// Profile version, and the page moves to that version's Verdicts.

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { QuestionField } from "../questionnaire";
import { api, trialsHref, type Answers, type LatestAnswers, type Question, type RespondentQuestion } from "@/lib/api";

type Loaded = { latest: LatestAnswers; byId: Record<string, Question>; version: string };

export function QuestionsForYou({ patientId, questions }: { patientId: string; questions: RespondentQuestion[] }) {
  const router = useRouter();
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [draft, setDraft] = useState<Answers>({});
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.definition(), api.latestAnswers(patientId)])
      .then(([definition, latest]) => {
        const byId = Object.fromEntries(definition.sections.flatMap((s) => s.questions).map((q) => [q.id, q]));
        setLoaded({ latest, byId, version: definition.version });
        setDraft(Object.fromEntries(questions.map((q) => [q.question_id, latest.answers[q.question_id] ?? ""])));
      })
      .catch((e: Error) => setError(e.message));
  }, [patientId, questions]);

  const changed = loaded !== null && questions.some(
    (q) => (draft[q.question_id] ?? "").trim() !== (loaded.latest.answers[q.question_id] ?? "").trim());

  async function send() {
    if (!loaded) return;
    setSending(true);
    setError(null);
    try {
      const answers: Answers = { ...loaded.latest.answers };
      for (const [id, value] of Object.entries(draft)) {
        if (value.trim()) answers[id] = value;
        else delete answers[id];
      }
      const r = await api.submit(patientId, { definition_version: loaded.version, respondent: loaded.latest.respondent,
                                              answers });
      if (r.outcome === "committed" && r.profile_version_id) router.push(trialsHref(patientId, r.profile_version_id));
      else setError(r.reason ?? "Your answers could not be saved. Please try again.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSending(false);
    }
  }

  return (
    <section aria-labelledby="questions-for-you" className="rounded-xl border border-border bg-surface p-5 flex flex-col gap-4">
      <h2 id="questions-for-you" className="text-lg font-semibold">Questions for you</h2>
      <p className="text-muted">
        A more exact answer to these would help decide some trials. A rough date is fine if that is all you know.
      </p>
      <ul className="flex flex-col gap-5">
        {questions.map((q) => {
          const question = loaded?.byId[q.question_id];
          return (
            <li key={q.question_id} className="flex flex-col gap-2">
              <p className="text-sm text-muted">
                {q.text} Helps decide {q.unblocks.length} trial{q.unblocks.length === 1 ? "" : "s"}.
              </p>
              {question && loaded ? (
                <QuestionField question={question} respondent={loaded.latest.respondent}
                               value={draft[q.question_id] || undefined}
                               onChange={(v) => setDraft((d) => ({ ...d, [q.question_id]: v }))}
                               onClear={() => setDraft((d) => ({ ...d, [q.question_id]: "" }))} />
              ) : (
                <p className="font-medium">{q.question} {q.subject}</p>
              )}
            </li>
          );
        })}
      </ul>
      {error && <p role="alert" className="text-red-700 dark:text-red-400">{error}</p>}
      <button type="button" onClick={send} disabled={!changed || sending}
              className="self-start min-h-12 rounded-lg bg-accent px-5 font-semibold text-white dark:text-black disabled:opacity-60">
        {sending ? "Saving and re-checking trials…" : "Send my answers"}
      </button>
    </section>
  );
}
