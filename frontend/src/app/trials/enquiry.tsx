"use client";

// An Enquiry: an email body for the Respondent to edit, copy and send themselves to the Trial's team. An Open trial's
// asks about taking part (#28); a Closed trial's, including one that stopped recruiting after it was judged, asks about
// its Outcomes or a follow-on study (#29). When first opened it lists the clinical details it may include, all ticked,
// and drafts nothing: no detail reaches the model until the Respondent has seen the list and asked for the draft.
// Unticking one and redrafting leaves it out of what the model sees. The draft lives only in this page: nothing is
// stored or sent.

import { useState } from "react";
import { api, type ClinicalDetailOut, type EnquiryOut } from "@/lib/api";

type State =
  | { kind: "closed" }
  | { kind: "loading" }
  | { kind: "error"; message: string; retry: () => void }
  | { kind: "choosing"; details: ClinicalDetailOut[]; ticked: Set<string> }
  | { kind: "drafting"; details: ClinicalDetailOut[]; ticked: Set<string> }
  | { kind: "ready"; details: ClinicalDetailOut[]; enquiry: EnquiryOut; body: string; ticked: Set<string> };

const RECIPIENT_KIND: Record<NonNullable<EnquiryOut["recipient"]>["kind"], string> = {
  site: "", central: "central contact", responsible_party: "responsible for the trial", official: "trial official",
};

export function Enquiry({ patientId, versionId, nctId, open = true }: {
  patientId: string; versionId: string; nctId: string; open?: boolean;   // open: the Trial is still recruiting
}) {
  const [state, setState] = useState<State>({ kind: "closed" });
  const [copied, setCopied] = useState(false);

  function offer() {
    setState({ kind: "loading" });
    api.enquiryDetails(patientId, versionId, nctId)
      .then((r) => setState({ kind: "choosing", details: r.details, ticked: new Set(r.details.map((d) => d.id)) }))
      .catch((e: Error) => setState({ kind: "error", message: e.message, retry: offer }));
  }

  function draft(details: ClinicalDetailOut[], ticked: Set<string>) {
    setState({ kind: "drafting", details, ticked });
    setCopied(false);
    api.enquiry(patientId, versionId, nctId, [...ticked])
      .then((enquiry) => setState({
        kind: "ready", details, enquiry, body: enquiry.body,
        ticked: new Set(enquiry.details.filter((d) => d.included).map((d) => d.id)),
      }))
      .catch((e: Error) => setState({ kind: "error", message: e.message, retry: () => draft(details, ticked) }));
  }

  function toggle(id: string) {
    if (state.kind !== "choosing" && state.kind !== "ready") return;
    const ticked = new Set(state.ticked);
    if (ticked.has(id)) ticked.delete(id);
    else ticked.add(id);
    setState({ ...state, ticked });
  }

  async function copy(text: string) {
    await navigator.clipboard.writeText(text);
    setCopied(true);
  }

  const checklist = (st: Extract<State, { kind: "choosing" | "drafting" | "ready" }>) => st.details.length > 0 && (
    <fieldset className="flex flex-col gap-1">
      <legend className="font-medium">Details to include</legend>
      <p className="text-muted">
        {st.kind === "ready"
          ? "Untick anything you would rather not share, then update the draft."
          : "These are the only details the email will mention. Untick anything you would rather not share."}
      </p>
      {st.details.map((d) => (
        <label key={d.id} className="flex items-start gap-2 min-h-11 py-2">
          <input type="checkbox" checked={st.ticked.has(d.id)} onChange={() => toggle(d.id)}
                 disabled={st.kind === "drafting"} className="mt-1 size-4" />
          <span>{d.label}: {d.text}</span>
        </label>
      ))}
    </fieldset>
  );

  return (
    <details onToggle={(e) => e.currentTarget.open && state.kind === "closed" && offer()}>
      <summary className="cursor-pointer min-h-11 flex items-center text-accent">
        {open ? "Ask about taking part" : "Ask about its results"}
      </summary>
      {state.kind === "loading" && <p className="text-muted">Loading…</p>}
      {state.kind === "error" && (
        <div role="alert" className="flex flex-col gap-2">
          <p className="text-red-700 dark:text-red-400">The email could not be drafted: {state.message}</p>
          <button type="button" onClick={state.retry} className="self-start min-h-11 text-accent underline">Try again</button>
        </div>
      )}
      {(state.kind === "choosing" || state.kind === "drafting") && (
        <div className="flex flex-col gap-4 mt-2 text-sm">
          <p className="text-muted">
            We can draft an email for you to edit and send yourself. We never send it or keep a copy.
          </p>
          {checklist(state)}
          {state.kind === "choosing" ? (
            <button type="button" onClick={() => draft(state.details, state.ticked)}
                    className="self-start min-h-12 rounded-lg bg-accent px-5 text-base font-semibold text-white dark:text-black">
              Draft the email
            </button>
          ) : <p className="text-muted">Drafting an email…</p>}
        </div>
      )}
      {state.kind === "ready" && (() => {
        const e = state.enquiry;
        const sent = new Set(e.details.filter((d) => d.included).map((d) => d.id));
        const changed = sent.size !== state.ticked.size || [...sent].some((id) => !state.ticked.has(id));
        return (
          <div className="flex flex-col gap-4 mt-2 text-sm">
            <p className="text-muted">
              We never send this or keep a copy. Edit it, copy it into your own email, and fill in your name and contact
              details where it says so.
            </p>
            <dl className="flex flex-col gap-2">
              <div className="flex flex-col gap-0.5">
                <dt className="text-muted">To</dt>
                <dd>
                  {e.recipient ? (
                    <>
                      {e.recipient.name} · <a href={`mailto:${e.recipient.email}`} className="text-accent underline">
                        {e.recipient.email}
                      </a>
                      <span className="text-muted">
                        {` (${e.recipient.kind === "site" ? e.recipient.facility : RECIPIENT_KIND[e.recipient.kind]})`}
                      </span>
                    </>
                  ) : (
                    <>
                      This trial lists no email address.
                      {e.sponsor && <> It is run by {e.sponsor}.</>} Open “Who to contact” on this trial for other
                      ways to reach them.
                    </>
                  )}
                </dd>
              </div>
              <div className="flex flex-col gap-0.5">
                <dt className="text-muted">Subject</dt>
                <dd>{e.subject}</dd>
              </div>
            </dl>
            {checklist(state)}
            {changed && (
              <button type="button" onClick={() => draft(state.details, state.ticked)}
                      className="self-start min-h-11 px-4 rounded-lg border border-border text-accent">
                Update the draft (replaces your edits)
              </button>
            )}
            <label className="flex flex-col gap-1">
              <span className="font-medium">Email</span>
              <textarea value={state.body} rows={14}
                        onChange={(ev) => { setState({ ...state, body: ev.target.value }); setCopied(false); }}
                        className="w-full rounded-lg border border-border bg-transparent px-3 py-2 text-base" />
            </label>
            <div className="flex items-center gap-3">
              <button type="button" onClick={() => copy(state.body)}
                      className="min-h-12 rounded-lg bg-accent px-5 text-base font-semibold text-white dark:text-black">
                Copy email
              </button>
              <span role="status" className="text-muted">{copied ? "Copied" : ""}</span>
            </div>
          </div>
        );
      })()}
    </details>
  );
}
