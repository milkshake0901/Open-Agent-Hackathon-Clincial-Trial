"use client";

// Shown once, after the first submission: the private link that reopens this patient's record.
// The server keeps only a hash of the token, so it cannot be shown again.

import { useState } from "react";

export function ReturnLink({ token }: { token: string }) {
  const [copied, setCopied] = useState(false);
  const url = `${window.location.origin}/return/${token}`;

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <section aria-labelledby="return-heading" className="rounded-xl border border-border bg-surface p-5 flex flex-col gap-3">
      <h2 id="return-heading" className="text-lg font-semibold">Your private return link</h2>
      <p>
        Save this link to come back to these answers later. There is no account or password: anyone with the link
        can see the answers, so keep it private. We can&apos;t show it again.
      </p>
      <input readOnly value={url} aria-label="Private return link" onFocus={(e) => e.target.select()}
             className="min-h-12 w-full rounded-lg border border-border bg-transparent px-3 text-base font-mono" />
      <button type="button" onClick={copy}
              className="self-start min-h-12 rounded-lg bg-accent px-5 text-base font-semibold text-white dark:text-black">
        {copied ? "Copied" : "Copy link"}
      </button>
      <p aria-live="polite" className="sr-only">{copied ? "Link copied" : ""}</p>
    </section>
  );
}
