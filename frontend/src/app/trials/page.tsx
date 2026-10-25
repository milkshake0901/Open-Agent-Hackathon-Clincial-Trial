import Link from "next/link";
import { Suspense } from "react";
import { ClosedTrials } from "./closed-trials";
import { TrialsList } from "./trials-list";

export default function TrialsPage({ searchParams }: PageProps<"/trials">) {
  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-8 flex flex-col gap-6">
      <header className="flex flex-col gap-2">
        <Link href="/" className="self-start text-sm text-accent underline">TrialMatch</Link>
        <h1 className="text-2xl font-semibold">Trials that might fit</h1>
        <p className="text-muted">
          This is a first look based on your answers. It does not mean you qualify: the trial team and your doctor
          decide that.
        </p>
      </header>
      <Suspense fallback={<p className="text-muted">Checking trials…</p>}>
        <ForVersion searchParams={searchParams} />
      </Suspense>
    </main>
  );
}

async function ForVersion({ searchParams }: Pick<PageProps<"/trials">, "searchParams">) {
  const params = await searchParams;
  const patient = typeof params.patient === "string" ? params.patient : null;
  const version = typeof params.version === "string" ? params.version : null;
  if (!patient || !version)
    return <p role="alert">This link is missing the patient or version. Start again from the questionnaire.</p>;
  return (
    <>
      <TrialsList patientId={patient} versionId={version} />
      <ClosedTrials patientId={patient} />
    </>
  );
}
