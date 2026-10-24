"use client";

// Opened from the private return link. Shows that patient's latest recorded answers and nothing else;
// an invalid link shows nothing about any patient.

import { useEffect, useState } from "react";
import { api, type VersionOut } from "@/lib/api";

type State =
  | { kind: "loading" }
  | { kind: "invalid" }
  | { kind: "empty" }
  | { kind: "ready"; version: VersionOut };

export function ReturnRecord({ token }: { token: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const opened = await api.openReturnLink(token);
        const next: State = opened.profile_version_id
          ? { kind: "ready", version: await api.version(opened.patient_id, opened.profile_version_id) }
          : { kind: "empty" };
        if (live) setState(next);
      } catch {
        if (live) setState({ kind: "invalid" });
      }
    })();
    return () => {
      live = false;
    };
  }, [token]);

  return (
    <>
      {state.kind === "loading" && <p className="text-muted">Opening your record…</p>}
      {state.kind === "invalid" && (
        <p role="alert">This link isn&apos;t valid. Check that you copied the whole link.</p>
      )}
      {state.kind === "empty" && <p>Nothing has been recorded yet.</p>}
      {state.kind === "ready" && (
        <section aria-labelledby="record-heading" className="rounded-xl border border-border bg-surface p-5 flex flex-col gap-4">
          <h2 id="record-heading" className="text-lg font-semibold">Your record, version {state.version.number}</h2>
          <p className="text-muted">What we recorded, and where each item came from.</p>
          <ul className="flex flex-col gap-3">
            {state.version.facts.map((f) => (
              <li key={f.id} className="rounded-lg border border-border p-3">
                <p className="font-medium first-letter:uppercase">{f.subject}</p>
                <p>“{f.citation.quote}”</p>
                <p className="text-sm text-muted">{f.citation.label}</p>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
