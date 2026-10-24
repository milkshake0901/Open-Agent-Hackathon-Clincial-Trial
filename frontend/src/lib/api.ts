// Wire types for the endpoints this page uses (backend/app/api/schemas.py).
// Hand-written for the tracer; replace with types generated from /openapi.json once more pages exist.

export type Option = { value: string; label: string };

export type Question = {
  id: string;
  number: number;
  label: string;
  label_other: string;
  kind: "month_year" | "single" | "multi" | "text" | "textarea" | "repeat";
  options: Option[];
  required: boolean;
  help: string | null;
};

export type Section = { id: string; title: string; questions: Question[] };
export type Questionnaire = { version: string; sections: Section[] };
export type Respondent = "patient" | "other";
export type Answers = Record<string, string>;

export type SubmissionAccepted = {
  run_id: string;
  outcome: "committed" | "awaiting_patient" | "rejected";
  document_hash: string | null;
  profile_version_id: string | null;
  version_number: number | null;
  reason: string | null;
  rescan: { judged: number; failed: number } | null;
  return_token: string | null; // first submission only
};

export type VerdictCitation = {
  fact_id: string;
  document_hash: string;
  page: number;
  quote: string;
  question: string | null;
  label: string;
};

export type CriterionResultOut = {
  criterion_id: string;
  kind: "inclusion" | "exclusion";
  text: string;
  outcome: "met" | "not_met" | "unknown";
  rationale: string;
  citation: VerdictCitation | null;
};

// criterion_id and nct_id are null on the patient-level diagnosis question (subject "diagnosis").
export type DoctorQuestion = {
  criterion_id: string | null;
  nct_id: string | null;
  subject: string;
  text: string;
  unblocks: string[];
};

export type DiagnosisCheck = {
  id: string;
  text: string;
  suggested_term: string | null;
  confidence: number;
  status: "proposed" | "confirmed" | "rejected" | "not_sure" | "unclear";
  condition: string | null;
  needs_gp: boolean;
  ask_again: boolean;
  message: string;
  rescan: { judged: number; failed: number } | null;
};

export type VerdictOut = {
  nct_id: string;
  title: string;
  status: string;
  profile_version_id: string;
  outcome: "eligible" | "possible" | "excluded";
  degraded: boolean;
  attempts: number;
  results: CriterionResultOut[];
  questions: DoctorQuestion[];
};

export type ReturnOpened = {
  patient_id: string;
  profile_version_id: string | null;
  version_number: number | null;
};

export type FactOut = {
  id: string;
  resource: string;
  subject: string;
  value: string;
  unit: string | null;
  observed_on: string;
  citation: { document_hash: string; page: number; quote: string; label: string };
};

export type VersionOut = {
  id: string;
  number: number;
  document_hash: string;
  facts: FactOut[];
  current: Record<string, string>;
};

export type UploadAccepted = { document_hash: string; run_id: string; deduplicated: boolean };

export type IngestPhase = "started" | "drafting" | "awaiting_patient" | "committed" | "rejected";

export type RunOut = {
  run_id: string;
  kind: "ingest" | "rescan";
  head: number;
  state: { phase: IngestPhase; version_number: number | null; reason: string | null } | null;
};

export type LatestAnswers = {
  definition_version: string;
  document_hash: string;
  respondent: Respondent;
  answers: Answers; // search preferences (postcode, travel, contact) are never included
};

export type VersionDiff = {
  from_version: string;
  to_version: string;
  facts_added: FactOut[];
  subjects_changed: { subject: string; before: FactOut | null; after: FactOut }[];
};

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const json = !(init?.body instanceof FormData); // the browser sets the multipart boundary itself
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { ...(json ? { "content-type": "application/json" } : {}), ...init?.headers },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  definition: () => call<Questionnaire>("/questionnaire/definition"),
  createPatient: (label: string) =>
    call<{ patient_id: string }>("/patients", { method: "POST", body: JSON.stringify({ label }) }),
  submit: (patientId: string, body: { definition_version: string; respondent: Respondent; answers: Answers }) =>
    call<SubmissionAccepted>(`/patients/${encodeURIComponent(patientId)}/questionnaire`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  upload: (patientId: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    return call<UploadAccepted>(`/patients/${encodeURIComponent(patientId)}/documents`, { method: "POST", body });
  },
  run: (runId: string) => call<RunOut>(`/runs/${encodeURIComponent(runId)}`),
  latestAnswers: (patientId: string) =>
    call<LatestAnswers>(`/patients/${encodeURIComponent(patientId)}/questionnaire`),
  diff: (patientId: string, versionId: string, fromVersionId: string) =>
    call<VersionDiff>(
      `/patients/${encodeURIComponent(patientId)}/versions/${encodeURIComponent(versionId)}/diff` +
        `?from=${encodeURIComponent(fromVersionId)}`,
    ),
  openReturnLink: (token: string) => call<ReturnOpened>(`/return/${encodeURIComponent(token)}`),
  version: (patientId: string, versionId: string) =>
    call<VersionOut>(`/patients/${encodeURIComponent(patientId)}/versions/${encodeURIComponent(versionId)}`),
  verdicts: (patientId: string, versionId: string) =>
    call<{ profile_version_id: string; verdicts: VerdictOut[] }>(
      `/patients/${encodeURIComponent(patientId)}/versions/${encodeURIComponent(versionId)}/verdicts`,
    ),
  checkDiagnosis: (patientId: string, text?: string) =>
    call<DiagnosisCheck>(`/patients/${encodeURIComponent(patientId)}/questionnaire/diagnosis-check`, {
      method: "POST",
      body: JSON.stringify(text ? { text } : {}),
    }),
  answerDiagnosis: (patientId: string, checkId: string, answer: "yes" | "no" | "not_sure") =>
    call<DiagnosisCheck>(
      `/patients/${encodeURIComponent(patientId)}/questionnaire/diagnosis-check/${encodeURIComponent(checkId)}`,
      { method: "POST", body: JSON.stringify({ answer }) },
    ),
  doctorQuestions: (patientId: string, versionId: string) =>
    call<DoctorQuestion[]>(
      `/patients/${encodeURIComponent(patientId)}/questions?version=${encodeURIComponent(versionId)}`,
    ),
};

export const trialsHref = (patientId: string, versionId: string) =>
  `/trials?patient=${encodeURIComponent(patientId)}&version=${encodeURIComponent(versionId)}`;
