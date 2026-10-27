// Renders the sketch's four views from window.TM (data.js). Hash routes: #/, #/questions, #/trial/<nct>,
// #/answers, #/documents.
(() => {
  const D = window.TM;
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const plural = (n, one, many = one + "s") => `${n} ${n === 1 ? one : many}`;
  const words = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"];
  const cap = (s) => s[0].toUpperCase() + s.slice(1);

  const verdictName = { eligible: "Matches what we know", possible: "May fit, needs checking", excluded: "Not a fit" };
  const resultName = { met: "Met", not: "Not met", unknown: "Not known yet" };
  const byNct = Object.fromEntries(D.trials.map((t) => [t.nct, t]));
  const latest = D.documents.at(-1);

  const site = (t) => `${esc(t.site.name)} · ${t.site.status} · <span class="num">${t.site.km} km</span>`;
  const checkNote = (t) => t.verdict === "possible" ? `${cap(words[t.unknowns])} ${t.unknowns === 1 ? "thing" : "things"} to check` : "";

  const rowCard = (t) => `
    <a class="rowcard" href="#/trial/${t.nct}">
      <span class="t">${esc(t.title)}</span>
      <span class="m">${site(t)}</span>
      <span class="r">${checkNote(t) ? `<span class="small muted">${checkNote(t)}</span>` : ""}<span class="pill ${t.verdict}">${verdictName[t.verdict]}</span></span>
    </a>`;

  // ---------- home ----------
  function home(scrollTo) {
    const near = D.trials.filter((t) => !t.furtherAway);
    const far = D.trials.filter((t) => t.furtherAway);
    const groups = ["eligible", "possible", "excluded"].map((v) => [v, near.filter((t) => t.verdict === v)]).filter(([, l]) => l.length);
    const nQ = D.youQuestions.length + D.doctorQuestions.length;

    $("#view").innerHTML = `
      <section class="greeting">
        <h1>${cap(words[D.counts.eligible])} trials match what we know</h1>
        <p class="sub">Updated ${latest.added}, after their ${latest.kind.toLowerCase()}. ${cap(words[D.counts.possible])} more may fit once a few things are checked. This doesn't replace their doctor's advice.</p>
        <div class="finding">
          <p>${cap(words[D.youQuestions.length])} questions only you can answer would help settle ${words[D.settledByYou]} trials.</p>
          <a class="btn primary" href="#/questions">Answer ${words[D.youQuestions.length]} questions</a>
        </div>
      </section>

      <div class="grid tiles">
        <a class="tile s3" href="#/"><span class="label">Match what we know</span><span class="value num">${D.counts.eligible}</span><span class="caption">${D.near("eligible")} within ${D.travelLimitKm} km</span></a>
        <a class="tile s3" href="#/"><span class="label">May fit, needs checking</span><span class="value num">${D.counts.possible}</span><span class="caption">${D.near("possible")} within ${D.travelLimitKm} km</span></a>
        <a class="tile s3" href="#/"><span class="label">Not a fit</span><span class="value num">${D.counts.excluded}</span><span class="caption">Kept here so you can see why</span></a>
        <a class="tile s3" href="#/questions"><span class="label">Questions waiting</span><span class="value num">${nQ}</span><span class="caption">${D.youQuestions.length} for you, ${D.doctorQuestions.length} for their doctor</span></a>
      </div>

      <div class="grid">
        <section class="panel s9" aria-labelledby="h-trials">
          <header><h2 id="h-trials">Trials within ${D.travelLimitKm} km <span class="chip">${near.length}</span></h2><span class="small muted">Nearest recruiting site first</span></header>
          ${groups.map(([v, list]) => `
            <div class="group-head"><strong>${verdictName[v]}</strong><span class="small num">${plural(list.length, "trial")}</span></div>
            <div class="rows">${list.map(rowCard).join("")}</div>`).join("")}
          <details class="further">
            <summary>Further away <span class="muted num">${plural(far.length, "trial")} beyond ${D.travelLimitKm} km</span></summary>
            <div class="rows">${far.map(rowCard).join("")}</div>
          </details>
        </section>

        <aside class="panel s3" aria-labelledby="h-changed">
          <header><h2 id="h-changed">What changed</h2></header>
          <ol class="ladder">
            ${D.documents.map((d, i) => `<li class="${i === D.documents.length - 1 ? "current" : ""}"><span class="v">Version ${d.version}</span><br><span class="small muted">${d.kind}, ${d.added}</span></li>`).join("")}
          </ol>
          <div class="moved">
            <p class="small muted">Since version ${D.version - 1}, ${plural(D.moved.length, "trial")} moved:</p>
            ${D.moved.map((t) => `
              <a href="#/trial/${t.nct}">
                <span class="mt">${esc(t.title)}</span>
                <span class="arrow"><span class="pill ${t.verdict}">${verdictName[t.verdict]}</span><span class="small muted">was ${verdictName[t.was].toLowerCase()}</span></span>
                <span class="small muted">${esc(t.moved)}</span>
              </a>`).join("")}
          </div>
          <div class="moved search">
            <p class="small muted">Searching for</p>
            <p>${esc(D.condition)}, within ${D.travelLimitKm} km of their postcode</p>
            <a class="link" href="#/answers">Change</a>
          </div>
        </aside>
      </div>

      <div class="grid" id="questions">
        <section class="panel s6" aria-labelledby="h-you">
          <header><h2 id="h-you">Questions for you <span class="chip">${D.youQuestions.length}</span></h2></header>
          <p class="lede">Things you might know. Answering updates the trials straight away.</p>
          ${D.youQuestions.map((q) => `
            <div class="q">
              <p class="qt">${esc(q.text)}</p>
              <p class="qm">You said: ${esc(q.said)} · would help ${plural(q.ncts.length, "trial")}</p>
              <div class="answer">${q.key === "thinners"
                ? `<div class="segmented" role="group" aria-label="Answer">${["Yes", "No", "Not sure"].map((a) => `<button type="button" aria-pressed="false">${a}</button>`).join("")}</div>`
                : `<label class="sr-only" for="a-${q.key}">Month and year</label><input class="input" id="a-${q.key}" placeholder="For example, around May 2025" style="max-width:300px"><button class="btn" type="button">Save</button>`}</div>
            </div>`).join("")}
        </section>

        <section class="panel s6" aria-labelledby="h-doc">
          <header><h2 id="h-doc">Questions for their doctor <span class="chip">${D.doctorQuestions.length}</span></h2><button class="btn ghost" type="button" onclick="window.print()">Print list</button></header>
          <p class="lede">These need medical records or a doctor's judgement. Take them to the next appointment.</p>
          ${D.doctorQuestions.map((q) => `
            <div class="q doctor">
              <p class="qt">${esc(q.text)}</p>
              <p class="unblocks small muted"><span class="n num">${q.ncts.length}</span> ${q.ncts.length === 1 ? "trial" : "trials"}</p>
            </div>`).join("")}
        </section>
      </div>

      <p class="foot">Sample data for a UI sketch. Trials, sites and distances are invented. TrialMatch never shows or stores a name, full date of birth or street address.</p>`;

    if (scrollTo) document.getElementById(scrollTo)?.scrollIntoView({ block: "start" });
  }

  // ---------- trial detail ----------
  function trial(nct) {
    const t = byNct[nct];
    if (!t) return home();
    const order = { unknown: 0, not: 1, met: 2 };
    const crits = [...t.criteria].sort((a, b) => order[a.result] - order[b.result]);
    const met = t.criteria.filter((c) => c.result === "met").length;
    const note = {
      eligible: "Everything this trial asks about matches what we know. Their doctor and the trial team still decide whether they can join.",
      possible: `This may be a fit. ${cap(words[t.unknowns])} ${t.unknowns === 1 ? "thing needs" : "things need"} checking before anyone can say more.`,
      excluded: "Something we know rules this trial out. It's kept here so you can see why, and so you can tell us if we got it wrong.",
    }[t.verdict];
    const asks = [...new Map(t.criteria.filter((c) => c.ask).map((c) => [c.ask.key, c.ask])).values()];
    const qText = (a) => a.to === "you" ? D.youQuestions.find((q) => q.key === a.key).text : D.doctorQuestions.find((q) => q.key === a.key).text;

    $("#view").innerHTML = `
      <a class="back" href="#/">← All trials</a>
      <section class="page-title">
        <h1>${esc(t.title)}</h1>
        <p class="sub"><span class="pill ${t.verdict}">${verdictName[t.verdict]}</span><span>${site(t)}</span><span class="num">${t.nct}</span></p>
        <p class="verdict-note">${note}</p>
      </section>

      <div class="grid top">
        <section class="panel s9" aria-labelledby="h-crit">
          <header><h2 id="h-crit">What the trial asks for <span class="chip">${t.criteria.length}</span></h2><span class="small muted num">${met} of ${t.criteria.length} met</span></header>
          ${crits.map((c) => `
            <div class="crit">
              <span class="pill ${c.result}">${resultName[c.result]}</span>
              <p class="ct">${esc(c.text)}</p>
              <p class="why">${esc(c.why)}</p>
              ${c.cite ? `<p class="cite"><a href="#/documents">${esc(c.cite.label)}</a></p>` : `<p class="cite">No document covers this yet</p>`}
              ${c.ask ? `<p class="route">${c.ask.to === "you" ? "A question for you" : "A question for their doctor"}</p>` : ""}
            </div>`).join("")}
        </section>

        <aside class="panel s3" aria-labelledby="h-site">
          <header><h2 id="h-site">Nearest site</h2></header>
          <dl class="facts">
            <div><dt>Distance</dt><dd class="big num">${t.site.km} km</dd></div>
            <div><dt>Hospital</dt><dd>${esc(t.site.name)}</dd></div>
            <div><dt>Status</dt><dd>${cap(t.site.status)}</dd></div>
            ${t.furtherAway ? `<div><dt>Travel</dt><dd>Beyond the ${D.travelLimitKm} km you said they'd travel</dd></div>` : ""}
          </dl>
          ${asks.length ? `<div class="moved"><p class="small muted">To settle this trial</p>${asks.map((a) => `<a href="#/questions"><span class="mt">${esc(qText(a))}</span><span class="small muted">${a.to === "you" ? "For you" : "For their doctor"}</span></a>`).join("")}</div>` : ""}
          <div class="moved"><a class="link" href="https://clinicaltrials.gov/study/${t.nct}" rel="noopener">Full listing on ClinicalTrials.gov</a></div>
        </aside>
      </div>`;
  }

  // ---------- questionnaire (one section) ----------
  function answers() {
    const rows = [
      { kind: "Chemotherapy", when: "October 2024 to around March 2025", ongoing: false },
      { kind: "Targeted therapy", when: "Since last year", ongoing: true },
    ];
    const kinds = ["Chemotherapy", "Radiotherapy", "Surgery", "Immunotherapy", "Targeted therapy", "Other"];
    const section = 4, total = 9;
    $("#view").innerHTML = `
      <a class="back" href="#/">← Back to trials</a>
      <section class="page-title">
        <h1>What treatment have they had so far?</h1>
        <div class="progress"><span class="small muted num">Section ${section} of ${total}: Treatment so far</span><div class="bar" role="progressbar" aria-valuenow="${section}" aria-valuemin="0" aria-valuemax="${total}" aria-label="Questionnaire progress"><span style="width:${(section / total) * 100}%"></span></div></div>
      </section>

      <div class="grid top">
        <section class="panel s9" aria-labelledby="h-treat">
          <header><h2 id="h-treat">Treatments <span class="chip">${rows.length}</span></h2><span class="saved">Saved</span></header>
          ${rows.map((r, i) => `
            <div class="treat">
              <div class="field"><label for="k${i}">Treatment</label><select class="input" id="k${i}">${kinds.map((k) => `<option${k === r.kind ? " selected" : ""}>${k}</option>`).join("")}</select></div>
              <div class="field"><label for="w${i}">Roughly when</label><input class="input" id="w${i}" value="${esc(r.when)}"></div>
              <div class="field"><span class="lab" id="o${i}">Still having it?</span><div class="segmented" role="group" aria-labelledby="o${i}"><button type="button" aria-pressed="${r.ongoing}">Yes</button><button type="button" aria-pressed="${!r.ongoing}">No</button></div></div>
              <button class="btn ghost" type="button" aria-label="Remove ${r.kind}">Remove</button>
            </div>`).join("")}
          <div class="form-foot">
            <button class="btn" type="button">Add another treatment</button>
          </div>
          <div class="form-foot">
            <a class="btn" href="#/answers">Back</a>
            <a class="btn primary" href="#/answers">Next: medicines now</a>
          </div>
        </section>

        <aside class="panel s3 help" aria-labelledby="h-why">
          <header><h2 id="h-why">Why we ask</h2></header>
          <p>Many trials only take people who have, or haven't, had a certain treatment, or who stopped it a while ago.</p>
          <p>Rough dates are fine. “Around March 2025” or “last winter” is better than nothing, and you can skip anything you don't know.</p>
          <p class="muted">Changing an answer later saves a new version. Earlier results stay visible.</p>
        </aside>
      </div>`;
  }

  // ---------- documents ----------
  function documents() {
    $("#view").innerHTML = `
      <section class="page-title">
        <h1>Documents and versions</h1>
        <p class="verdict-note">Each document you add makes a new version of what we know, and the trials are checked again. Names and addresses are removed before anything reads them.</p>
      </section>
      <div class="grid top">
        <section class="panel s9" aria-labelledby="h-docs">
          <header><h2 id="h-docs">Added so far <span class="chip">${D.documents.length}</span></h2></header>
          <div class="rows">${[...D.documents].reverse().map((d) => `
            <div class="rowcard doc"><span class="t">${d.kind}</span><span class="m num">${plural(d.pages, "page")} · added ${d.added}</span><span class="r">Version ${d.version}</span></div>`).join("")}</div>
        </section>
        <aside class="panel s3" aria-labelledby="h-add">
          <header><h2 id="h-add">Add a letter or report</h2></header>
          <div class="drop"><p class="muted">Referral letters, blood tests, scan and genomic reports help most.</p><button class="btn primary" type="button">Choose files</button></div>
        </aside>
      </div>`;
  }

  // ---------- first-contact flow ----------
  // No sidebar until there are results: a wordmark, where they are in the flow, and one way forward.
  const F = D.flow;
  const their = (mine, theirs) => (D.respondent === "patient" ? mine : theirs);
  const stages = [["who", "Who's answering"], ["answers", "Questions"], ["diagnosis", "Diagnosis check"], ["uploads", "Documents"], ["return", "Your link"]];
  const stageStrip = (at) => `
    <ol class="stages" aria-label="Where you are">${stages.map(([id, label], i) => {
      const k = stages.findIndex(([s]) => s === at);
      return `<li class="${i < k ? "done" : i === k ? "now" : ""}"${i === k ? ' aria-current="step"' : ""}>${label}</li>`;
    }).join("")}</ol>`;
  const flowFoot = (back, next, nextLabel, extra = "") => `
    <div class="form-foot">
      <a class="btn" href="#/${back}">Back</a>
      <span class="foot-right">${extra}<a class="btn primary" href="#/${next}">${nextLabel}</a></span>
    </div>`;

  function welcome() {
    $("#view").innerHTML = `
      <section class="greeting">
        <h1>Find clinical trials that might fit</h1>
        <p class="sub">Answer some plain questions about yourself, or about the person you're helping. We check them against every recruiting trial on ClinicalTrials.gov, explain each result, and tell you what to ask the doctor.</p>
      </section>
      <div class="grid">
        <section class="panel s9" aria-labelledby="h-before">
          <header><h2 id="h-before">Before you start</h2></header>
          <dl class="promise">
            <div><dt>About ${F.minutes} minutes</dt><dd>Skip anything you don't know. Rough dates like “around March” are fine.</dd></div>
            <div><dt>Save and come back</dt><dd>You get a private link at the end. There's no account or password.</dd></div>
            <div><dt>Only what trials need</dt><dd>We never ask for a name, a full date of birth, a street address or a Medicare number.</dd></div>
            <div><dt>Not medical advice</dt><dd>Results are a starting point for a talk with the doctor, who decides what's right.</dd></div>
          </dl>
          <div class="form-foot"><span></span><a class="btn primary" href="#/who">Start</a></div>
        </section>
        <aside class="panel s3" aria-labelledby="h-need">
          <header><h2 id="h-need">What you'll need</h2></header>
          <p>Nothing, to begin with. Letters and reports make results more accurate, and you can add them at the end or any time later.</p>
          <div class="moved search"><p class="small muted">Already started?</p><a class="link" href="#/return">Use your private link</a></div>
        </aside>
      </div>`;
  }

  const sections = [
    ["About", "Birth month and year, sex"], ["Where", "Postcode, how far to travel"], ["Diagnosis", "In your own words"],
    ["Treatment so far", "Rough dates are fine"], ["Medicines now", "Names, if you know them"], ["Allergies", "If any"],
    ["Other health", "Heart, kidney, liver and others"], ["Daily activity", "What a usual day is like"], ["Pregnancy", "Optional"],
  ];
  function who() {
    const opt = (id, title, body, example) => `
      <label class="choice s6">
        <input type="radio" name="who" value="${id}"${D.respondent === id ? " checked" : ""}>
        <span class="ct">${title}</span>
        <span>${body}</span>
        <span class="example">Questions will read: <em>${example}</em></span>
      </label>`;
    $("#view").innerHTML = `
      ${stageStrip("who")}
      <section class="page-title"><h1>Who is answering?</h1>
        <p class="verdict-note">Family members and carers often fill this in. We'll word every question to suit.</p></section>
      <div class="grid choices" role="radiogroup" aria-label="Who is answering">
        ${opt("patient", "I'm the patient", "I'm looking for trials for myself.", "“When were you diagnosed?”")}
        ${opt("other", "I'm answering for someone else", "I'm a family member, partner, friend or carer helping them.", "“When were they diagnosed?”")}
      </div>
      <div class="grid"><section class="panel s12" aria-labelledby="h-next">
        <header><h2 id="h-next">Next, ${sections.length} short sections <span class="chip">about ${F.minutes} min</span></h2><span class="small muted">Only birth month, sex, postcode and diagnosis are needed</span></header>
        <ul class="sections">${sections.map(([t, d]) => `<li><span class="t">${t}</span><span class="small muted">${d}</span></li>`).join("")}</ul>
      </section></div>
      ${flowFoot("start", "answers", "Next: about " + their("you", "them"))}`;
    document.querySelectorAll('input[name="who"]').forEach((r) => r.addEventListener("change", () => { D.respondent = r.value; who(); }));
  }

  function diagnosis(pick) {
    const replies = {
      yes: `<p>Thanks. We'll search for trials for <strong>${F.suggested.term.toLowerCase()}</strong>.</p>`,
      no: `<div class="field"><label for="reword">Tell us again in other words</label><textarea class="input area" id="reword" rows="3">${esc(F.diagnosisWords)}</textarea><span class="small muted">Words from a letter or scan report help, if you have one.</span></div><div><button class="btn" type="button" data-pick="retry">Check again</button></div>`,
      unsure: `<p>That's fine. We'll search more broadly for now and add “What is the exact type of lung cancer?” to the questions for ${their("your", "their")} doctor. Their GP can confirm it from the biopsy report.</p>`,
      retry: `<p class="muted">Checking your new wording…</p>`,
    };
    $("#view").innerHTML = `
      ${stageStrip("diagnosis")}
      <section class="page-title"><h1>Did we understand the diagnosis?</h1>
        <p class="verdict-note">We use this to choose which trials to check, so it's worth getting right.</p></section>
      <div class="grid">
        <section class="panel s9" aria-labelledby="h-understood">
          <div class="quote"><p class="small muted">You wrote</p><blockquote>“${esc(F.diagnosisWords)}”</blockquote><p class="small muted">Diagnosed: ${esc(F.diagnosedWhen)}</p></div>
          <div class="understood"><p class="small muted" id="h-understood">We understood this as</p><p class="term">${F.suggested.term}</p></div>
          <p class="lab" id="is-right">Is that right?</p>
          <div class="answer-row" role="group" aria-labelledby="is-right">
            ${[["yes", "Yes"], ["no", "No, let me re-word it"], ["unsure", "Not sure"]].map(([k, l]) => `<button class="btn" type="button" data-pick="${k}" aria-pressed="${pick === k}">${l}</button>`).join("")}
          </div>
          ${pick ? `<div class="reply" role="status">${replies[pick]}</div>` : ""}
          ${flowFoot("answers", "uploads", "Next: documents")}
        </section>
        <aside class="panel s3" aria-labelledby="h-why2">
          <header><h2 id="h-why2">Why we ask</h2></header>
          <p>Trials are listed under formal names. “Lung cancer” alone matches hundreds of trials that aren't for this kind.</p>
          <p class="muted">Your own words stay on file exactly as you wrote them.</p>
        </aside>
      </div>`;
    document.querySelectorAll("[data-pick]").forEach((b) => b.addEventListener("click", () => diagnosis(b.dataset.pick)));
  }

  function uploads() {
    const done = F.files.filter((f) => f.state === "done").length;
    const stateText = { done: "Read", checking: "Reading now", waiting: "Waiting" };
    $("#view").innerHTML = `
      ${stageStrip("uploads")}
      <section class="page-title"><h1>Have letters or reports?</h1>
        <p class="verdict-note">Adding them makes results more accurate. You can skip this and add them any time from ${their("your", "the")} trials page.</p></section>
      <div class="grid">
        <section class="panel s9" aria-labelledby="h-files">
          <header><h2 id="h-files">Checking ${words[F.files.length]} documents <span class="chip num">${done} of ${F.files.length}</span></h2></header>
          <div class="progress wide"><div class="bar" role="progressbar" aria-valuenow="${done}" aria-valuemin="0" aria-valuemax="${F.files.length}" aria-label="Documents checked"><span style="width:${(done / F.files.length) * 100}%"></span></div>
            <p class="small muted">Removing names and addresses, then reading each page. You can carry on while this runs.</p></div>
          <div class="rows">${F.files.map((f) => `
            <div class="rowcard"><span class="t">${esc(f.name)}</span><span class="m num">${plural(f.pages, "page")}</span><span class="r"><span class="pill ${f.state === "done" ? "met" : f.state === "checking" ? "unknown" : ""}">${stateText[f.state]}</span><button class="btn ghost" type="button">Remove</button></span></div>`).join("")}</div>
          <div class="drop slim"><p class="muted">Drop more files here, or</p><button class="btn" type="button">Choose files</button></div>
          ${flowFoot("diagnosis", "return", "Continue", `<a class="btn ghost" href="#/return">Skip for now</a>`)}
        </section>
        <aside class="panel s3" aria-labelledby="h-helps">
          <header><h2 id="h-helps">What helps most</h2></header>
          <ul class="plain"><li>The latest referral or specialist letter</li><li>Recent blood test results</li><li>Genomic or biomarker reports</li><li>Scan reports, especially of the brain</li></ul>
          <p class="muted">Photos of paper letters work too. PDF, JPG or PNG.</p>
        </aside>
      </div>`;
  }

  function returnLink() {
    $("#view").innerHTML = `
      ${stageStrip("return")}
      <section class="page-title"><h1>Keep this private link</h1>
        <p class="verdict-note">It's the only way back to ${their("your", "their")} answers and results. There's no account or password.</p></section>
      <div class="grid">
        <section class="panel s9" aria-labelledby="h-link">
          <header><h2 id="h-link">Your private link</h2></header>
          <div class="joined"><label class="sr-only" for="rl">Private link</label><input class="input" id="rl" value="${F.returnLink}" readonly><button class="btn" type="button" id="copy-return">Copy link</button></div>
          <p class="small muted note">Anyone with this link can see the answers, so share it only with people you trust. Bookmark it, or email it to yourself.</p>

          <div class="optional">
            <p class="lab">Tell me when there are new questions <span class="muted">(optional)</span></p>
            <p class="small muted">We'll only use this to say something needs an answer. It's never shown to a model or shared.</p>
            <div class="field"><label for="contact">Email or mobile number</label><input class="input" id="contact" placeholder="For example, 0412 345 678" autocomplete="off"></div>
          </div>
          ${flowFoot("uploads", "", "See trials")}
        </section>
        <aside class="panel s3" aria-labelledby="h-now">
          <header><h2 id="h-now">What happens now</h2></header>
          <p>We're checking trials against ${their("your", "their")} answers. First results usually take a few minutes.</p>
          <p class="muted">When a document you added is read, the results update and show what changed.</p>
        </aside>
      </div>`;
    $("#copy-return").addEventListener("click", (e) => { e.currentTarget.textContent = "Copied"; });
  }

  // ---------- routing ----------
  const flowRoutes = { start: welcome, who, diagnosis: () => diagnosis(), uploads, return: returnLink };
  function route() {
    const h = location.hash.replace(/^#\/?/, "");
    const [name, arg] = h.split("/");
    document.body.classList.toggle("flow", name in flowRoutes);
    if (name in flowRoutes) { window.scrollTo(0, 0); flowRoutes[name](); closeMenu(); return; }
    const current = name === "trial" ? "home" : name || "home";
    document.querySelectorAll(".nav-item").forEach((a) => {
      if (a.dataset.route === current) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
    window.scrollTo(0, 0);
    if (name === "trial") trial(arg);
    else if (name === "questions") home("questions");
    else if (name === "answers") answers();
    else if (name === "documents") documents();
    else home();
    closeMenu();
  }

  // Segmented controls toggle within their group.
  document.addEventListener("click", (e) => {
    const b = e.target.closest(".segmented button");
    if (!b) return;
    b.parentElement.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  });

  const side = $("#sidebar"), menu = $("#menu");
  const closeMenu = () => { side.classList.remove("open"); menu.setAttribute("aria-expanded", "false"); };
  menu.addEventListener("click", () => { side.classList.add("open"); menu.setAttribute("aria-expanded", "true"); });
  $("#close").addEventListener("click", closeMenu);
  $("#copy-link").addEventListener("click", (e) => { e.currentTarget.textContent = "Link copied"; });

  $("#nav-trials").textContent = D.trials.length;
  $("#nav-questions").textContent = D.youQuestions.length + D.doctorQuestions.length;
  $("#nav-docs").textContent = D.documents.length;

  addEventListener("hashchange", route);
  route();
})();
