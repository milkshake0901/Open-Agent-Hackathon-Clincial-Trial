"use client";

// Who to contact about a Trial (#27): its central contact, overall official, sponsor and responsible party, each
// Australian Trial site's facility and contacts, and its ClinicalTrials.gov page. Loaded when first opened.

import { useState, type ReactNode } from "react";
import { api, type ContactOut, type TrialDetail } from "@/lib/api";

type State = { kind: "closed" } | { kind: "loading" } | { kind: "error"; message: string } | { kind: "ready"; trial: TrialDetail };

const words = (code: string) => code.toLowerCase().replaceAll("_", " ");

export function TrialContacts({ nctId }: { nctId: string }) {
  const [state, setState] = useState<State>({ kind: "closed" });

  function load() {
    if (state.kind !== "closed") return;
    setState({ kind: "loading" });
    api.trial(nctId)
      .then((trial) => setState({ kind: "ready", trial }))
      .catch((e: Error) => setState({ kind: "error", message: e.message }));
  }

  return (
    <details onToggle={(e) => e.currentTarget.open && load()}>
      <summary className="cursor-pointer min-h-11 flex items-center text-accent">Who to contact</summary>
      {state.kind === "loading" && <p className="text-muted">Loading contacts…</p>}
      {state.kind === "error" && (
        <p role="alert" className="text-red-700 dark:text-red-400">Contacts could not be loaded: {state.message}</p>
      )}
      {state.kind === "ready" && <ContactList trial={state.trial} />}
    </details>
  );
}

function ContactList({ trial: t }: { trial: TrialDetail }) {
  const people: [string, ContactOut[]][] = [
    ["Central contact", t.central_contacts],
    ["Overall official", t.overall_officials],
    ["Responsible party", t.responsible_party ? [t.responsible_party] : []],
  ];
  return (
    <div className="flex flex-col gap-3 mt-2 text-sm">
      <dl className="flex flex-col gap-2">
        {t.sponsor && <Entry label="Sponsor">{t.sponsor}</Entry>}
        {people.filter(([, cs]) => cs.length > 0).map(([label, cs]) => (
          <Entry key={label} label={label}>{cs.map((c, i) => <ContactLine key={i} contact={c} />)}</Entry>
        ))}
      </dl>
      {t.sites.length > 0 && (
        <section className="flex flex-col gap-2">
          <h4 className="font-medium">Australian sites</h4>
          <ul className="flex flex-col gap-2">
            {t.sites.map((s, i) => (
              <li key={i} className="rounded-lg border border-border p-3 flex flex-col gap-1">
                <p>{s.facility}, {s.city}{s.status && <span className="text-muted"> · {words(s.status)}</span>}</p>
                {s.contacts.length === 0
                  ? <p className="text-muted">No site contact listed</p>
                  : s.contacts.map((c, j) => <ContactLine key={j} contact={c} />)}
              </li>
            ))}
          </ul>
        </section>
      )}
      <p>
        <a href={t.page_url} className="text-accent underline" rel="noreferrer" target="_blank">
          See this trial on ClinicalTrials.gov
        </a>
      </p>
    </div>
  );
}

function Entry({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-muted">{label}</dt>
      <dd className="flex flex-col gap-1">{children}</dd>
    </div>
  );
}

function ContactLine({ contact: c }: { contact: ContactOut }) {
  const who = [c.title, c.name].filter(Boolean).join(" ");
  const about = [c.role && c.role !== "CONTACT" ? words(c.role) : "", c.affiliation].filter(Boolean).join(", ");
  return (
    <p>
      {who}{about && <span className="text-muted"> ({about})</span>}
      {c.email && <> · <a href={`mailto:${c.email}`} className="text-accent underline">{c.email}</a></>}
      {c.phone && <> · <a href={`tel:${c.phone.replace(/[^+\d]/g, "")}`} className="text-accent underline">{c.phone}</a></>}
    </p>
  );
}
