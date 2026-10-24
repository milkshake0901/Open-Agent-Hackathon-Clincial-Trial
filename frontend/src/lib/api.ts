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

export type DoctorQuestion = { criterion_id: string; nct_id: string; subject: string; text: string; unblocks: string[] };

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

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...init?.headers },
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
  version: (patientId: string, versionId: string) =>
    call<VersionOut>(`/patients/${encodeURIComponent(patientId)}/versions/${encodeURIComponent(versionId)}`),
  verdicts: (patientId: string, versionId: string) =>
    call<{ profile_version_id: string; verdicts: VerdictOut[] }>(
      `/patients/${encodeURIComponent(patientId)}/versions/${encodeURIComponent(versionId)}/verdicts`,
    ),
  doctorQuestions: (patientId: string, versionId: string) =>
    call<DoctorQuestion[]>(
      `/patients/${encodeURIComponent(patientId)}/questions?version=${encodeURIComponent(versionId)}`,
    ),
};

export const trialsHref = (patientId: string, versionId: string) =>
  `/trials?patient=${encodeURIComponent(patientId)}&version=${encodeURIComponent(versionId)}`;
