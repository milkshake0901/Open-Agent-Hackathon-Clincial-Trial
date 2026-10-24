"use client";

// A generic renderer for the Intake questionnaire definition served by the backend. No question is
// hard-coded here except the one that says who is answering, whose answer switches "your" / "their".

import { useEffect, useState } from "react";
import { api, type Answers, type Question, type Questionnaire, type Respondent, type VersionOut } from "@/lib/api";
import { DocumentUploads } from "./uploads";

const RESPONDENT_QUESTION = "respondent";

type Status =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; definition: Questionnaire };

export function QuestionnaireForm() {
  const [status, setStatus] = useState<Status>({ kind: "loading" });
  const [answers, setAnswers] = useState<Answers>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [saved, setSaved] = useState<{ patientId: string; version: VersionOut } | null>(null);

  useEffect(() => {
    api
      .definition()
      .then((definition) => setStatus({ kind: "ready", definition }))
      .catch((e: Error) => setStatus({ kind: "error", message: e.message }));
  }, []);

  if (status.kind === "loading") return <p className="text-muted">Loading the questionnaire…</p>;
  if (status.kind === "error")
    return (
      <p role="alert" className="text-red-700 dark:text-red-400">
        The questionnaire could not be loaded: {status.message}
      </p>
    );

  const respondent: Respondent = answers[RESPONDENT_QUESTION] === "other" ? "other" : "patient";
  const set = (id: string, value: string) => setAnswers((a) => ({ ...a, [id]: value }));
  const clear = (id: string) =>
    setAnswers((a) => {
      const next = { ...a };
      delete next[id];
      return next;
    });

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (status.kind !== "ready") return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const { patient_id } = await api.createPatient("Web respondent");
      const result = await api.submit(patient_id, {
        definition_version: status.definition.version,
        respondent,
        answers,
      });
      if (result.outcome !== "committed" || !result.profile_version_id) {
        throw new Error(result.reason ?? "Your answers could not be recorded yet.");
      }
      setSaved({ patientId: patient_id, version: await api.version(patient_id, result.profile_version_id) });
    } catch (err) {
      setSubmitError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  if (saved)
    return (
      <div className="flex flex-col gap-6">
        <ProfileSummary version={saved.version} />
        <DocumentUploads patientId={saved.patientId} />
      </div>
    );

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-6" noValidate>
      <p className="text-muted">Every question can be skipped. We never ask for a name or a street address.</p>
      {status.definition.sections.map((section) => (
        <section key={section.id} aria-labelledby={`section-${section.id}`}
                 className="rounded-xl border border-border bg-surface p-5 flex flex-col gap-5">
          <h2 id={`section-${section.id}`} className="text-lg font-semibold">{section.title}</h2>
          {section.questions.map((q) => (
            <QuestionField key={q.id} question={q} respondent={respondent} value={answers[q.id]}
                           onChange={(v) => set(q.id, v)} onClear={() => clear(q.id)} />
          ))}
        </section>
      ))}
      {submitError && <p role="alert" className="text-red-700 dark:text-red-400">{submitError}</p>}
      <button type="submit" disabled={submitting}
              className="min-h-12 rounded-lg bg-accent px-5 text-base font-semibold text-white dark:text-black disabled:opacity-60">
        {submitting ? "Saving your answers…" : "Save answers"}
      </button>
    </form>
  );
}

function QuestionField({ question: q, respondent, value, onChange, onClear }: {
  question: Question;
  respondent: Respondent;
  value: string | undefined;
  onChange: (v: string) => void;
  onClear: () => void;
}) {
  const id = `q-${q.id}`;
  const label = `${respondent === "patient" ? q.label : q.label_other}`;
  const help = q.help ? <p id={`${id}-help`} className="text-sm text-muted">{q.help}</p> : null;
  const describedBy = q.help ? `${id}-help` : undefined;
  const input = "min-h-12 w-full rounded-lg border border-border bg-transparent px-3 text-base";

  if (q.kind === "single") {
    return (
      <fieldset className="flex flex-col gap-2" aria-describedby={describedBy}>
        <legend className="font-medium mb-1">
          <span className="text-muted mr-2">Q{q.number}</span>{label}
        </legend>
        {help}
        {q.options.map((o) => (
          <label key={o.value} className="flex min-h-11 items-center gap-3 rounded-lg border border-border px-3">
            <input type="radio" name={id} value={o.value} checked={value === o.value}
                   onChange={() => onChange(o.value)} className="h-5 w-5" />
            {o.label}
          </label>
        ))}
        {value !== undefined && (
          <button type="button" onClick={onClear} className="self-start text-sm text-accent underline">
            Clear this answer
          </button>
        )}
      </fieldset>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className="font-medium">
        <span className="text-muted mr-2">Q{q.number}</span>{label}
      </label>
      {help}
      {q.kind === "month_year" ? (
        <input id={id} type="month" className={input} value={value ?? ""} aria-describedby={describedBy}
               onChange={(e) => (e.target.value ? onChange(e.target.value) : onClear())} />
      ) : q.kind === "text" ? (
        <input id={id} type="text" className={input} value={value ?? ""} aria-describedby={describedBy}
               autoComplete="off" onChange={(e) => onChange(e.target.value)} />
      ) : (
        <textarea id={id} rows={3} className={`${input} py-2`} value={value ?? ""} aria-describedby={describedBy}
                  onChange={(e) => onChange(e.target.value)} />
      )}
    </div>
  );
}

function ProfileSummary({ version }: { version: VersionOut }) {
  return (
    <section aria-labelledby="profile-heading" className="rounded-xl border border-border bg-surface p-5 flex flex-col gap-4">
      <h2 id="profile-heading" className="text-lg font-semibold">Thank you. Your answers are saved as version {version.number}.</h2>
      <p className="text-muted">This is what we recorded, and where each item came from.</p>
      <ul className="flex flex-col gap-3">
        {version.facts.map((f) => (
          <li key={f.id} className="rounded-lg border border-border p-3">
            <p className="font-medium first-letter:uppercase">{f.subject}</p>
            <p>“{f.citation.quote}”</p>
            <p className="text-sm text-muted">{f.citation.label}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
