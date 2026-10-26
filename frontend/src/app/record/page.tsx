import Link from "next/link";
import { Suspense } from "react";
import { LetterQuestion } from "./letter";
import { MatchingTrialsList } from "./matching";

// Canvas 1200px, side padding 24px, one 24px gutter: 420 + 24 + the letter column.

export default function RecordPage({ searchParams }: PageProps<"/record">) {
  return (
    <main className="mx-auto flex w-full max-w-[1200px] flex-col gap-6 px-6 py-8">
      <header className="flex flex-col gap-2">
        <Link href="/" className="self-start text-sm text-accent underline">
          TrialMatch
        </Link>
        <h1 className="text-2xl font-semibold">mCRPC trials for this referral</h1>
        <p className="text-muted">
          Stored Australian trials whose condition name is metastatic castration-resistant prostate cancer,
          including the short form mCRPC. The letter below is the referral.
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
  return (
    <>
      <MatchingTrialsList patientId={patient} />
      <LetterQuestion patientId={patient} />
    </>
  );
}
