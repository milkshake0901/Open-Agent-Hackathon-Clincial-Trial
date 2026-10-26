"use client";

// What a Citation points at, drawn from the Citation alone: the letter page with its Region boxed, or the Intake
// questionnaire answer with the quoted part highlighted. Used by the Trials page's side panel for a Criterion
// result's Citation, and for anything else shaped like one.

import type { VerdictCitation } from "@/lib/api";
import { RegionPage } from "@/app/region-page";

// Whether a Citation has a source the panel can show.
export function hasSource(c: VerdictCitation): boolean {
  return Boolean(c.region || c.answer);
}

// The button text that opens a Citation's source.
export function sourceLabel(c: VerdictCitation): string {
  return c.answer ? "Show your answer" : "Show where the letter says this";
}

export function CitationSource({ citation: c }: { citation: VerdictCitation }) {
  if (c.answer) return <AnswerQuote citation={c} answer={c.answer} />;
  if (!c.region) return null;
  return (
    <>
      <blockquote className="border-l-4 border-accent pl-3">“{c.quote}”</blockquote>
      <RegionPage documentHash={c.document_hash} page={c.page} filename={c.filename ?? "letter"}
                  boxes={[c.region]} active={c.region.span_id} />
    </>
  );
}

function AnswerQuote({ citation: c, answer: a }: {
  citation: VerdictCitation;
  answer: NonNullable<VerdictCitation["answer"]>;
}) {
  const found = a.quote_start !== null && a.quote_end !== null;
  return (
    <figure className="flex flex-col gap-2 rounded-lg border border-border p-3">
      <figcaption className="text-sm text-muted">Intake questionnaire, {c.question}</figcaption>
      <p className="font-medium">{a.wording}</p>
      <p>
        {found ? (
          <>
            {a.text.slice(0, a.quote_start!)}
            <mark className="rounded bg-accent/25 px-0.5 text-inherit">{a.text.slice(a.quote_start!, a.quote_end!)}</mark>
            {a.text.slice(a.quote_end!)}
          </>
        ) : a.text}
      </p>
      {!found && <blockquote className="border-l-4 border-accent pl-3 text-sm">Read as: “{c.quote}”</blockquote>}
      <a href={`/#${c.question}`} className="text-sm text-accent underline">Go to this question</a>
    </figure>
  );
}
