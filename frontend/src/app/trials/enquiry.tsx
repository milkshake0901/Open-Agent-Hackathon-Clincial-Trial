"use client";

// An Enquiry (#28): an email body asking the Trial's team about taking part, for the Respondent to edit, copy and
// send themselves. Drafted when first opened, with every clinical detail ticked; unticking one and redrafting
// leaves it out of what the model sees. The draft lives only in this page: nothing is stored or sent.

import { useState } from "react";
import { api, type EnquiryOut } from "@/lib/api";

type State =
  | { kind: "closed" }
  | { kind: "drafting" }
  | { kind: "error"; message: string }
  | { kind: "ready"; enquiry: EnquiryOut; body: string; ticked: Set<string> };

export function Enquiry({ patientId, versionId, nctId }: { patientId: string; versionId: string; nctId: string }) {
  const [state, setState] = useState<State>({ kind: "closed" });
  const [copied, setCopied] = useState(false);

  function draft(include?: string[]) {
    setState({ kind: "drafting" });
    setCopied(false);
    api.enquiry(patientId, versionId, nctId, include)
      .then((enquiry) => setState({
        kind: "ready", enquiry, body: enquiry.body,
        ticked: new Set(enquiry.details.filter((d) => d.included).map((d) => d.id)),
      }))
      .catch((e: Error) => setState({ kind: "error", message: e.message }));
  }

  function toggle(id: string) {
    if (state.kind !== "ready") return;
    const ticked = new Set(state.ticked);
    if (ticked.has(id)) ticked.delete(id);
    else ticked.add(id);
    setState({ ...state, ticked });
  }

  async function copy(text: string) {
    await navigator.clipboard.writeText(text);
    setCopied(true);
  }

  return (
    <details onToggle={(e) => e.currentTarget.open && state.kind === "closed" && draft()}>
      <summary className="cursor-pointer min-h-11 flex items-center text-accent">Ask about taking part</summary>
      {state.kind === "drafting" && <p className="text-muted">Drafting an email…</p>}
      {state.kind === "error" && (
        <div role="alert" className="flex flex-col gap-2">
          <p className="text-red-700 dark:text-red-400">The email could not be drafted: {state.message}</p>
          <button type="button" onClick={() => draft()} className="self-start min-h-11 text-accent underline">Try again</button>
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
                        {e.recipient.kind === "site" ? ` (${e.recipient.facility})` : " (central contact)"}
                      </span>
                    </>
                  ) : (
                    <>
                      This trial lists no email address.
                      {e.sponsor && <> It is run by {e.sponsor}.</>} See “Who to contact” for other ways to reach them.
                    </>
                  )}
                </dd>
              </div>
              <div className="flex flex-col gap-0.5">
                <dt className="text-muted">Subject</dt>
                <dd>{e.subject}</dd>
              </div>
            </dl>
            {e.details.length > 0 && (
              <fieldset className="flex flex-col gap-1">
                <legend className="font-medium">Details to include</legend>
                <p className="text-muted">Untick anything you would rather not share, then update the draft.</p>
                {e.details.map((d) => (
                  <label key={d.id} className="flex items-start gap-2 min-h-11 py-2">
                    <input type="checkbox" checked={state.ticked.has(d.id)} onChange={() => toggle(d.id)}
                           className="mt-1 size-4" />
                    <span>{d.label}: {d.text}</span>
                  </label>
                ))}
                {changed && (
                  <button type="button" onClick={() => draft([...state.ticked])}
                          className="self-start min-h-11 px-4 rounded-lg border border-border text-accent">
                    Update the draft (replaces your edits)
                  </button>
                )}
              </fieldset>
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
