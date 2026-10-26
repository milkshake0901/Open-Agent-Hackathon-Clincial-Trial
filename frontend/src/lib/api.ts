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

// A Condition label as stored Trials list it, with how many Open and Closed trials list it (ADR 0005).
export type ConditionLabel = { label: string; open: number; closed: number };

// The diagnosis step, as the Trials page sees it: labels ticked (the Condition term), answered not sure (it waits on
// the GP), or neither yet.
export type Diagnosis = "ticked" | "not_sure" | "unfinished";

export type DiagnosisAnswer =
  | { answer: "ticked"; labels: string[] }
  | { answer: "none_of_these"; text: string } // the diagnosis in other words: returns the new check
  | { answer: "not_sure" };

export type DiagnosisCheck = {
  id: string;
  text: string;
  shortlist: ConditionLabel[]; // best fit first; empty when no label fits
  ticked: string[]; // status "ticked": the Condition term, the labels that select Trials
  status: "proposed" | "ticked" | "not_sure";
  needs_gp: boolean;
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
  no_longer_recruiting: boolean; // closed after it was judged: the Verdict is kept, never re-judged
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

// A Closed trial: it can no longer enrol, so it has no Verdict; shown for what it studied and when it finished.
export type ClosedTrialOut = {
  nct_id: string;
  title: string;
  status: string;
  conditions: string[];
  closed_on: string | null; // ISO date: primary completion, else completion, else last update
  url: string;
};

// Registry fields it does not give are "".
export type ContactOut = { name: string; role: string; email: string; phone: string; affiliation: string; title: string };

// A Trial's Outcomes (#25). Registry fields it does not give are "".
export type OutcomeMeasureOut = { measure: string; description: string; time_frame: string };

export type PostedResultOut = {
  type: string; // PRIMARY, SECONDARY, OTHER_PRE_SPECIFIED or POST_HOC
  title: string;
  description: string;
  time_frame: string;
  unit: string;
  param_type: string; // e.g. MEDIAN, MEAN, COUNT_OF_PARTICIPANTS
  values: { group: string; value: string; spread: string; lower: string; upper: string; label: string }[];
};

export type OutcomesOut = {
  primary: OutcomeMeasureOut[];
  secondary: OutcomeMeasureOut[];
  other: OutcomeMeasureOut[];
  has_results: boolean;
  results: PostedResultOut[];
  publications: { pmid: string; type: string; citation: string; url: string }[]; // url "" without a PubMed id
};

// A plain-language summary of a Trial's Outcomes (#26), written by the model on first open and cached after.
export type OutcomeSummaryOut = { nct_id: string; summary: string };

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
  outcomes: OutcomesOut;
};

// An Enquiry (#28 Open trial, #29 Closed trial): an email body the Respondent edits, copies and sends themselves.
// Never stored or sent. Its clinical details are fetched first (no model call) and drafted only once confirmed.
export type ClinicalDetailOut = { id: string; label: string; text: string; included: boolean };
export type EnquiryOut = {
  nct_id: string;
  template: "open" | "closed";
  subject: string;
  body: string; // name and contact are placeholders the Respondent fills in
  recipient: { name: string; email: string; kind: "site" | "central" | "responsible_party" | "official"; facility: string | null } | null; // null: no email listed
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

export type GroundedCitation = {
  span_id: string;
  document_hash: string;
  filename: string;
  page: number;
  quote: string;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
};

export type AskAnswer = {
  answer: "yes" | "no" | "unknown";
  reasoning: string;
  as_of: string;
  patient_label: string;
  document_hash: string;
  filename: string;
  page_count: number;
  citations: GroundedCitation[];
};

const enquiryPath = (patientId: string, versionId: string, nctId: string) =>
  `/patients/${encodeURIComponent(patientId)}/versions/${encodeURIComponent(versionId)}` +
  `/trials/${encodeURIComponent(nctId)}/enquiry`;

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
    call<{ profile_version_id: string; condition_term: string[] | null; diagnosis: Diagnosis; verdicts: VerdictOut[] }>(
      `/patients/${encodeURIComponent(patientId)}/versions/${encodeURIComponent(versionId)}/verdicts`,
    ),
  closedTrials: (patientId: string) =>
    call<{ condition_term: string[] | null; trials: ClosedTrialOut[] }>(
      `/patients/${encodeURIComponent(patientId)}/closed-trials`,
    ),
  trial: (nctId: string) => call<TrialDetail>(`/trials/${encodeURIComponent(nctId)}`),
  outcomeSummary: (nctId: string) => call<OutcomeSummaryOut>(`/trials/${encodeURIComponent(nctId)}/outcomes/summary`),
  enquiryDetails: (patientId: string, versionId: string, nctId: string) =>
    call<{ nct_id: string; details: ClinicalDetailOut[] }>(enquiryPath(patientId, versionId, nctId)),
  enquiry: (patientId: string, versionId: string, nctId: string, include: string[]) =>
    call<EnquiryOut>(enquiryPath(patientId, versionId, nctId), { method: "POST", body: JSON.stringify({ include }) }),
  checkDiagnosis: (patientId: string) =>
    call<DiagnosisCheck>(`/patients/${encodeURIComponent(patientId)}/questionnaire/diagnosis-check`, {
      method: "POST",
    }),
  // none_of_these returns the new check made from its new words.
  answerDiagnosis: (patientId: string, checkId: string, answer: DiagnosisAnswer) =>
    call<DiagnosisCheck>(
      `/patients/${encodeURIComponent(patientId)}/questionnaire/diagnosis-check/${encodeURIComponent(checkId)}`,
      { method: "POST", body: JSON.stringify(answer) },
    ),
  doctorQuestions: (patientId: string, versionId: string) =>
    call<DoctorQuestion[]>(
      `/patients/${encodeURIComponent(patientId)}/questions?version=${encodeURIComponent(versionId)}`,
    ),
  ask: (patientId: string, question: string) =>
    call<AskAnswer>(`/patients/${encodeURIComponent(patientId)}/ask`, {
      method: "POST",
      body: JSON.stringify({ question }),
    }),
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
