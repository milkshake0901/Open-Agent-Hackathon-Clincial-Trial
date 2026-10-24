import { Suspense } from "react";
import { ReturnRecord } from "./return-record";

export default function ReturnPage({ params }: PageProps<"/return/[token]">) {
  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-8 flex flex-col gap-6">
      <h1 className="text-2xl font-semibold">TrialMatch</h1>
      <Suspense fallback={<p className="text-muted">Opening your record…</p>}>
        <WithToken params={params} />
      </Suspense>
    </main>
  );
}

async function WithToken({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <ReturnRecord token={token} />;
}
