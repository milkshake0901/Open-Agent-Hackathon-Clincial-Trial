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

// A questionnaire submission, like an added Document: its Document and the run to follow for the outcome.
export type QuestionnaireAccepted = {
  document_hash: string;
  run_id: string;
  deduplicated: boolean;
  return_token: string | null; // first submission only
};

// The outcome of answering a Conflict (POST /runs/{id}/confirm).
export type IngestOutcome = {
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

// Asks the Respondent to answer a questionnaire question again, more exactly; answering resubmits the questionnaire.
export type RespondentQuestion = {
  criterion_id: string;
  nct_id: string;
  question_id: string;
  question: string; // "Q8"
  subject: string;
  text: string;
  unblocks: string[];
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
  respondent_questions: RespondentQuestion[];
  nearest_site: SiteOut | null; // nearest recruiting site
  sites: SiteOut[]; // up to 3 nearest open sites, any status
  further_away: boolean; // no recruiting site within the travel limit
};

export type SiteOut = { name: string; status: string; km: number | null };

// Registry fields it does not give are "".
export type ContactOut = { name: string; role: string; email: string; phone: string; affiliation: string; title: string };

export type TrialDetail = {
  nct_id: string;
  title: string;
  status: string;
  page_url: string; // the Trial's ClinicalTrials.gov page
  sponsor: string;
  responsible_party: ContactOut | null;
  central_contacts: ContactOut[];
  overall_officials: ContactOut[];
  sites: { facility: string; city: string; status: string; contacts: ContactOut[] }[]; // Australian sites only
};

// An Enquiry (#28): an email body the Respondent edits, copies and sends themselves. Never stored or sent.
export type ClinicalDetailOut = { id: string; label: string; text: string; included: boolean };
export type EnquiryOut = {
  nct_id: string;
  template: "open" | "closed";
  subject: string;
  body: string; // name and contact are placeholders the Respondent fills in
  recipient: { name: string; email: string; kind: "site" | "central"; facility: string | null } | null; // null: no email listed
  sponsor: string;
  details: ClinicalDetailOut[];
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

export type DocumentAccepted = { document_hash: string; run_id: string; deduplicated: boolean };

export type IngestPhase = "started" | "drafting" | "awaiting_patient" | "committed" | "rejected";

export type RunOut = {
  run_id: string;
  kind: "ingest" | "rescan";
  head: number;
  state: {
    phase: IngestPhase;
    profile_version_id: string | null;
    version_number: number | null;
    reason: string | null;
  } | null;
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

export type ConflictSide = {
  document_hash: string;
  filename: string;
  page: number;
  page_text: string; // de-identified
  quote: string;
  value: string;
  unit: string | null;
  observed_on: string | null;
  label: string; // "Patient-reported, intake questionnaire, Q13" or "referral.pdf, page 2"
};

export type ConflictOut = { id: string; message: string; draft: ConflictSide; accepted: ConflictSide | null };

export type Resolution = { conflict_id: string; choice: "keep_accepted" | "accept_draft" | "discard_both" };

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
    call<QuestionnaireAccepted>(`/patients/${encodeURIComponent(patientId)}/questionnaire`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  addDocument: (patientId: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    return call<DocumentAccepted>(`/patients/${encodeURIComponent(patientId)}/documents`, { method: "POST", body });
  },
  run: (runId: string) => call<RunOut>(`/runs/${encodeURIComponent(runId)}`),
  conflicts: (runId: string) =>
    call<{ run_id: string; conflicts: ConflictOut[] }>(`/runs/${encodeURIComponent(runId)}/conflicts`),
  confirm: (runId: string, resolutions: Resolution[]) =>
    call<IngestOutcome>(`/runs/${encodeURIComponent(runId)}/confirm`, {
      method: "POST",
      body: JSON.stringify({ resolutions }),
    }),
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
  trial: (nctId: string) => call<TrialDetail>(`/trials/${encodeURIComponent(nctId)}`),
  enquiry: (patientId: string, versionId: string, nctId: string, include?: string[]) =>
    call<EnquiryOut>(
      `/patients/${encodeURIComponent(patientId)}/versions/${encodeURIComponent(versionId)}` +
        `/trials/${encodeURIComponent(nctId)}/enquiry`,
      { method: "POST", body: JSON.stringify(include ? { include } : {}) },
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
  respondentQuestions: (patientId: string, versionId: string) =>
    call<RespondentQuestion[]>(
      `/patients/${encodeURIComponent(patientId)}/respondent-questions?version=${encodeURIComponent(versionId)}`,
    ),
};

export const trialsHref = (patientId: string, versionId: string) =>
  `/trials?patient=${encodeURIComponent(patientId)}&version=${encodeURIComponent(versionId)}`;

const POLL_MS = 1000;
const ENDED = new Set<IngestPhase>(["committed", "rejected", "awaiting_patient"]);

// Ingest runs in the background after an added Document or a questionnaire submission; poll it until it ends.
export async function followRun(runId: string): Promise<RunOut> {
  for (;;) {
    const run = await api.run(runId);
    if (run.state && ENDED.has(run.state.phase)) return run;
    await new Promise((r) => setTimeout(r, POLL_MS));
  }
}
