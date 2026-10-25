import Link from "next/link";
import { Suspense } from "react";
import { LetterQuestion } from "./letter";

// Canvas 1200px, side padding 24px, one 24px gutter: 420 + 24 + the letter column.

export default function RecordPage({ searchParams }: PageProps<"/record">) {
  return (
    <main className="mx-auto flex w-full max-w-[1200px] flex-col gap-6 px-6 py-8">
      <header className="flex flex-col gap-2">
        <Link href="/" className="self-start text-sm text-accent underline">
          TrialMatch
        </Link>
        <h1 className="text-2xl font-semibold">Has this patient had chemotherapy in the last ten days?</h1>
        <p className="text-muted">
          The answer is read from the referral letter. The highlighted region is the part of the page it used.
        </p>
      </header>
      <Suspense fallback={<p className="text-muted">Opening the letter…</p>}>
        <ForPatient searchParams={searchParams} />
      </Suspense>
    </main>
  );
}

async function ForPatient({ searchParams }: Pick<PageProps<"/record">, "searchParams">) {
  const params = await searchParams;
  const patient = typeof params.patient === "string" ? params.patient : "pt_referral_20260209";
  return <LetterQuestion patientId={patient} />;
}
