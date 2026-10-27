// Sample data for the UI sketch. Every Trial, site and Fact here is invented for the sketch and must be
// replaced by the API (docs/ui/ui-brief.md). Counts on screen are computed from these rows, never typed.

window.TM = (() => {
  const respondent = "other"; // "patient" | "other": switches "your" / "their"
  const travelLimitKm = 50;
  const condition = "Non-small cell lung cancer with an EGFR change"; // the confirmed condition term

  const documents = [
    { id: "doc-intake", kind: "Intake questionnaire", added: "23 Oct 2026", pages: 9, version: 1 },
    { id: "doc-referral", kind: "Referral letter", added: "24 Oct 2026", pages: 2, version: 2 },
    { id: "doc-genomic", kind: "Genomic report", added: "24 Oct 2026", pages: 4, version: 3 },
  ];

  // Citation sources. q = questionnaire question number, p = page.
  const src = {
    q: (n, section) => ({ doc: "doc-intake", label: n ? `You told us (intake questionnaire, Q${n})` : "You told us (who is answering)", section }),
    p: (doc, page) => ({ doc, page, label: `${documents.find((d) => d.id === doc).kind}, page ${page}` }),
  };

  // Criterion results: met | not | unknown. `ask` routes an unknown to exactly one question list.
  const C = (text, result, why, cite, ask) => ({ text, result, why, cite, ask });

  const askDoctor = {
    progression: "Has the cancer grown while on osimertinib? A recent scan report would show this.",
    brainMri: "Has there been a brain MRI in the last 4 weeks?",
    spots: "How many spots of cancer are there outside the lung?",
  };
  const askYou = {
    osimertinibStart: { text: "Which month did they start osimertinib (Tagrisso)?", said: "“Tagrisso, since last year”", question: 7 },
    thinners: { text: "Are they taking a blood thinner, such as warfarin, apixaban or rivaroxaban?", said: "No answer yet", question: 7 },
  };

  const common = [
    C("Aged 18 or over", "met", "Born March 1958, so 68 today.", src.q(1, "About")),
    C("Non-small cell lung cancer, confirmed by biopsy", "met", "The referral letter gives the biopsy result.", src.p("doc-referral", 1)),
  ];

  const trials = [
    {
      nct: "NCT06100001", title: "A blood test to track EGFR changes during osimertinib",
      site: { name: "Westmead Hospital", status: "recruiting", km: 23 }, verdict: "eligible", was: "possible",
      moved: "The genomic report confirmed the EGFR exon 19 deletion.",
      criteria: [...common,
        C("EGFR mutation found", "met", "Exon 19 deletion.", src.p("doc-genomic", 2)),
        C("Currently taking osimertinib", "met", "Listed under medicines now.", src.q(7, "Medicines now"))],
    },
    {
      nct: "NCT06100002", title: "Gentle exercise during targeted therapy for lung cancer",
      site: { name: "Liverpool Hospital", status: "recruiting", km: 14 }, verdict: "eligible", was: "eligible",
      criteria: [...common,
        C("Up and about most of the day", "met", "“Up and about, gets tired in the afternoon.”", src.q(12, "Daily activity")),
        C("No heart condition that limits exercise", "met", "None ticked under other health.", src.q(10, "Other health"))],
    },
    {
      nct: "NCT06100003", title: "Amivantamab with lazertinib after osimertinib",
      site: { name: "Chris O'Brien Lifehouse", status: "recruiting", km: 28 }, verdict: "possible", was: "possible",
      criteria: [...common,
        C("EGFR exon 19 deletion or L858R", "met", "Exon 19 deletion.", src.p("doc-genomic", 2)),
        C("Cancer has grown on osimertinib", "unknown", "Nothing we have says whether it has grown.", null, { to: "doctor", key: "progression" }),
        C("Osimertinib for at least 6 months", "unknown", "“Since last year” could be under or over 6 months.", src.q(7, "Medicines now"), { to: "you", key: "osimertinibStart" }),
        C("No chemotherapy in the last 4 weeks", "met", "Chemotherapy ended around March 2025.", src.q(6, "Treatment so far")),
        C("Kidney function in range", "met", "eGFR 78 mL/min.", src.p("doc-referral", 2))],
    },
    {
      nct: "NCT06100004", title: "Adding targeted radiotherapy to osimertinib",
      site: { name: "Royal North Shore Hospital", status: "recruiting", km: 31 }, verdict: "possible", was: "possible",
      criteria: [...common,
        C("Five or fewer spots of cancer outside the lung", "unknown", "The referral letter says “several” without a count.", src.p("doc-referral", 1), { to: "doctor", key: "spots" }),
        C("Brain MRI in the last 4 weeks", "unknown", "No brain scan in the documents.", null, { to: "doctor", key: "brainMri" }),
        C("Not taking a blood thinner", "unknown", "Medicines now doesn't mention one either way.", src.q(7, "Medicines now"), { to: "you", key: "thinners" })],
    },
    {
      nct: "NCT06100005", title: "A new EGFR tablet when osimertinib stops working",
      site: { name: "Peter MacCallum Cancer Centre", status: "recruiting", km: 714 }, verdict: "possible", was: "possible",
      criteria: [...common,
        C("Cancer has grown on osimertinib", "unknown", "Nothing we have says whether it has grown.", null, { to: "doctor", key: "progression" }),
        C("Brain MRI in the last 4 weeks", "unknown", "No brain scan in the documents.", null, { to: "doctor", key: "brainMri" }),
        C("Osimertinib for at least 6 months", "unknown", "“Since last year” could be under or over 6 months.", src.q(7, "Medicines now"), { to: "you", key: "osimertinibStart" })],
    },
    {
      nct: "NCT06100006", title: "Support calls for carers of people on lung cancer tablets",
      site: { name: "Calvary Mater Newcastle", status: "recruiting", km: 152 }, verdict: "eligible", was: "eligible",
      criteria: [...common,
        C("Has a family member or carer involved", "met", "You are answering for them.", src.q(0, "Who is answering"))],
    },
    {
      nct: "NCT06100007", title: "Chemotherapy-free first treatment for EGFR lung cancer",
      site: { name: "Westmead Hospital", status: "recruiting", km: 23 }, verdict: "excluded", was: "excluded",
      criteria: [...common,
        C("No earlier treatment for advanced cancer", "not", "Carboplatin and pemetrexed, ended around March 2025.", src.q(6, "Treatment so far"))],
    },
    {
      nct: "NCT06100008", title: "Immunotherapy for lung cancer without an EGFR change",
      site: { name: "Liverpool Hospital", status: "recruiting", km: 14 }, verdict: "excluded", was: "possible",
      moved: "The genomic report found an EGFR change, which this trial excludes.",
      criteria: [...common,
        C("No EGFR mutation", "not", "Exon 19 deletion found.", src.p("doc-genomic", 2))],
    },
  ];

  const order = { eligible: 0, possible: 1, excluded: 2 };
  const unknowns = (t) => t.criteria.filter((c) => c.result === "unknown").length;
  for (const t of trials) {
    t.unknowns = unknowns(t);
    t.furtherAway = t.site.km > travelLimitKm;
  }
  // Rank: Verdict, then fewest unknowns (possible), then nearest recruiting site. Distance never changes a Verdict.
  trials.sort((a, b) => order[a.verdict] - order[b.verdict] || a.unknowns - b.unknowns || a.site.km - b.site.km);

  // Questions, deduplicated by subject, each carrying the Trials it would unblock.
  const collect = (to, table) => Object.entries(table).map(([key, q]) => ({
    key, ...(typeof q === "string" ? { text: q } : q),
    ncts: trials.filter((t) => t.criteria.some((c) => c.ask?.to === to && c.ask.key === key)).map((t) => t.nct),
  })).filter((q) => q.ncts.length).sort((a, b) => b.ncts.length - a.ncts.length);
  const youQuestions = collect("you", askYou);
  const doctorQuestions = collect("doctor", askDoctor);

  const count = (v) => trials.filter((t) => t.verdict === v).length;
  const counts = { eligible: count("eligible"), possible: count("possible"), excluded: count("excluded") };
  const near = (v) => trials.filter((t) => t.verdict === v && !t.furtherAway).length;
  const settledByYou = new Set(youQuestions.flatMap((q) => q.ncts)).size;

  // What changed from the previous Profile version.
  const prev = { eligible: 0, possible: 0, excluded: 0 };
  for (const t of trials) prev[t.was]++;
  const moved = trials.filter((t) => t.was !== t.verdict);

  console.assert(counts.eligible + counts.possible + counts.excluded === trials.length, "verdicts sum to trials");
  console.assert(prev.eligible + prev.possible + prev.excluded === trials.length, "previous verdicts sum to trials");
  console.assert(trials.every((t) => t.criteria.filter((c) => c.result === "unknown").every((c) => c.ask)), "every unknown raises one question");
  console.assert(trials.filter((t) => t.verdict === "eligible").every((t) => t.unknowns === 0), "eligible has no unknowns");

  // First-contact flow: what the Respondent typed, what the backend suggested, what they attached.
  const flow = {
    minutes: 10,
    diagnosisWords: "Lung cancer, the EGFR kind. It has spread to some bones.",
    diagnosedWhen: "Around September 2024",
    suggested: { term: "Non-small cell lung cancer", confidence: 0.86 },
    files: [
      { name: "Referral letter.pdf", pages: 2, state: "done" },
      { name: "Blood results September.pdf", pages: 1, state: "checking" },
      { name: "Genomic report.pdf", pages: 4, state: "waiting" },
    ],
    returnLink: "https://trialmatch.example/r/k7Qm-2fXa-9pLe",
  };
  console.assert(flow.files.every((f) => ["done", "checking", "waiting"].includes(f.state)), "file states");

  return {
    flow,
    respondent, travelLimitKm, condition, documents, trials, youQuestions, doctorQuestions, counts, near, settledByYou,
    prev, moved, version: documents.length, updated: documents.at(-1).added,
  };
})();
