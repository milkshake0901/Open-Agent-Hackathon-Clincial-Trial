import { QuestionnaireForm } from "./questionnaire";

export default function Home() {
  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-8 flex flex-col gap-6">
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold">TrialMatch</h1>
        <p>
          A few plain-language questions help us look for clinical trials that might fit. It does not replace
          advice from a doctor.
        </p>
      </header>
      <QuestionnaireForm />
    </main>
  );
}
