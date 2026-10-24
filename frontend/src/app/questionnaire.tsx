"use client";

// A generic renderer for the Intake questionnaire definition served by the backend. No question is
// hard-coded here except the one that says who is answering, whose answer switches "your" / "their".

import { useEffect, useState } from "react";
import Link from "next/link";
import { DiagnosisCheckCard } from "./diagnosis-check";
import { ReturnLink } from "./return-link";
import { DocumentUploads } from "./uploads";
import {
  api, followRun, trialsHref, type Answers, type Question, type Questionnaire, type Respondent, type VersionDiff,
  type VersionOut,
} from "@/lib/api";

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
  const [version, setVersion] = useState<VersionOut | null>(null);
  const [changes, setChanges] = useState<VersionDiff | null>(null);
  const [patientId, setPatientId] = useState<string | null>(null);
  const [savedVersionId, setSavedVersionId] = useState<string | null>(null);
  const [loadingEdit, setLoadingEdit] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [returnToken, setReturnToken] = useState<string | null>(null);

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
      // A correction is a full resubmission for the same patient: a new Profile version.
      const patient_id = patientId ?? (await api.createPatient("Web respondent")).patient_id;
      setPatientId(patient_id);
      const accepted = await api.submit(patient_id, {
        definition_version: status.definition.version,
        respondent,
        answers,
      });
      setReturnToken((t) => accepted.return_token ?? t); // issued on the first submission only
      // The answers are checked in the background, like an added letter or report: follow the run.
      const state = (await followRun(accepted.run_id)).state!;
      if (state.phase !== "committed" || !state.profile_version_id) {
        throw new Error(state.reason ?? "Your answers could not be recorded yet.");
      }
      const versionId = state.profile_version_id;
      setVersion(await api.version(patient_id, versionId));
      setChanges(savedVersionId && savedVersionId !== versionId
        ? await api.diff(patient_id, versionId, savedVersionId)
        : null);
      setSavedVersionId(versionId);
    } catch (err) {
      setSubmitError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  async function onEdit() {
    if (!patientId) return;
    setLoadingEdit(true);
    setEditError(null);
    try {
      // Prefill from the latest accepted submission, not from what this page happens to remember.
      const latest = await api.latestAnswers(patientId);
      setAnswers({ ...latest.answers, [RESPONDENT_QUESTION]: latest.respondent });
      setVersion(null);
      setChanges(null);
      window.scrollTo({ top: 0 });
    } catch (err) {
      setEditError((err as Error).message);
    } finally {
      setLoadingEdit(false);
    }
  }

  if (version) {
    return (
      <div className="flex flex-col gap-4">
        {patientId && answers.diagnosis && <DiagnosisCheckCard key={version.id} patientId={patientId} />}
        <ProfileSummary version={version} changes={changes} patientId={patientId} />
        {returnToken && <ReturnLink token={returnToken} />}
        {patientId && <DocumentUploads patientId={patientId} />}
        {editError && <p role="alert" className="text-red-700 dark:text-red-400">{editError}</p>}
        <button type="button" onClick={onEdit} disabled={loadingEdit}
                className="min-h-12 self-start rounded-lg border border-border px-5 text-base font-semibold disabled:opacity-60">
          {loadingEdit ? "Opening your answers…" : "Edit answers"}
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-6" noValidate>
      <p className="text-muted">Every question can be skipped. We never ask for a name or a street address.</p>
      {patientId && (
        <p className="text-muted">
          You are editing your saved answers. Saving sends the whole questionnaire again and keeps the earlier version.
          Your postcode and contact details are not shown again; leave them blank to keep what you gave before.
        </p>
      )}
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

export function QuestionField({ question: q, respondent, value, onChange, onClear }: {
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
      <fieldset id={`Q${q.number}`} className="flex flex-col gap-2 scroll-mt-4" aria-describedby={describedBy}>
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
    <div id={`Q${q.number}`} className="flex flex-col gap-2 scroll-mt-4">
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

function ProfileSummary({ version, changes, patientId }: {
  version: VersionOut;
  changes: VersionDiff | null;
  patientId: string | null;
}) {
  return (
    <section aria-labelledby="profile-heading" className="rounded-xl border border-border bg-surface p-5 flex flex-col gap-4">
      <h2 id="profile-heading" className="text-lg font-semibold">Thank you. Your answers are saved as version {version.number}.</h2>
      {patientId && (
        <div className="flex flex-col gap-2">
          <p>We are checking your answers against trials now. The list fills in as each trial is checked.</p>
          <Link href={trialsHref(patientId, version.id)}
                className="self-start min-h-12 inline-flex items-center rounded-lg bg-accent px-5 font-semibold text-white dark:text-black">
            See trials that might fit
          </Link>
        </div>
      )}
      {changes && (
        <div className="flex flex-col gap-2">
          <h3 className="font-semibold">What changed since the previous version</h3>
          {changes.subjects_changed.length === 0 ? (
            <p className="text-muted">None of the recorded answers changed.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {changes.subjects_changed.map((c) => (
                <li key={c.subject} className="rounded-lg border border-accent p-3">
                  <p className="font-medium first-letter:uppercase">{c.subject}</p>
                  <p>
                    {c.before ? <>“{c.before.citation.quote}” → </> : null}“{c.after.citation.quote}”
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <p className="text-muted">This is what we recorded, and where each item came from.</p>
      <ul className="flex flex-col gap-3">
        {version.facts.filter((f) => version.current[f.subject] === f.id).map((f) => (
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
