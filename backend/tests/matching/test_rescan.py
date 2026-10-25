"""Seam 2 (spec #5): the matching facade. Profile v1 comes from a questionnaire (record facade), Trials from the
saved ClinicalTrials.gov snapshot (trials facade); a Re-scan judges them through the Matcher ⇄ Evaluator loop with a
scripted fake model. Observed through verdict, verdicts_for_version, questions_for_version and the captured prompts."""
from __future__ import annotations

import json
from pathlib import Path

from app import matching, record, trials
from app.llm.nightshift import FakeLLM
from tests.condition_term import tick_condition_term

SNAPSHOT = Path(__file__).resolve().parents[3] / "data" / "trials_snapshot"
NCT = trials.NctId("NCT07680790")
ANSWERS = {"birth_month": "1958-03", "sex": "female", "daily_activity": "fully_active", "postcode": "2031"}


def script(fake, matcher, judge=None):
    """Script the fake model: `matcher(user_prompt)` answers each Matcher call with a results list;
    `judge(user_prompt)` answers each Evaluator support check (default: every cited claim is supported)."""
    def respond(lane, system, user):
        if lane == "deep":
            return {"results": matcher(user)}
        if lane == "judge":
            if judge is not None:
                return {"checks": judge(user)}
            ids = [line.split()[1] for line in user.splitlines() if line.startswith("CLAIM ")]
            return {"checks": [{"criterion_id": c, "supported": True, "reason": "stated"} for c in ids]}
        raise AssertionError(f"unexpected {lane} call")
    fake.responder = respond


async def _setup(clean_db, answers=ANSWERS, snapshot=SNAPSHOT):
    """Trials loaded from the snapshot, a Condition term selecting all of them, and Profile v1 committed from
    structured answers (no model call captured yet)."""
    from tests.conftest import make_ctx
    fake = FakeLLM()
    ctx = make_ctx(clean_db, fake)
    await trials.load_snapshot(ctx, snapshot)
    patient = await record.create_patient(ctx, "Demo patient M")
    await tick_condition_term(ctx, patient)
    outcome = await record.submit_questionnaire(ctx, patient, answers, respondent="other")
    assert isinstance(outcome, record.Committed)
    return ctx, fake, await record.profile_version(ctx, outcome.version.id)


def answer_all(criteria, met=(), outcome="met", fact=None):
    """A Matcher answer: criteria whose text contains a string in `met` get `outcome` citing `fact`; the rest unknown."""
    def matcher(user):
        return [{"criterion_id": c.id, "outcome": outcome, "fact_id": fact.id if fact else None, "rationale": "per record"}
                if any(m in c.text for m in met) else
                {"criterion_id": c.id, "outcome": "unknown", "fact_id": None, "rationale": "not in the record"}
                for c in criteria]
    return matcher


async def test_a_rescan_of_profile_v1_stores_a_cited_verdict_for_the_snapshot_trial(clean_db):
    ctx, fake, version = await _setup(clean_db)
    criteria = await trials.criteria(ctx, NCT)
    activity = version.current()["daily activity"]
    script(fake, answer_all(criteria, met=("ECOG",), fact=activity))

    report = await matching.rescan(ctx, version.id)

    assert report.judged == (NCT,) and report.failed == ()
    v = await matching.verdict(ctx, NCT, version.id)
    assert v is not None and v.outcome == "possible"
    texts = {c.id: c.text for c in criteria}
    ecog = next(r for r in v.results if "ECOG" in texts[r.criterion_id])
    assert ecog.outcome == "met"
    assert ecog.citation.fact_id == activity.id
    assert ecog.citation.quote == "Fully active, doing everything as before the illness"
    assert ecog.citation.question == "Q13"
    assert all(r.citation is None for r in v.results if r.outcome == "unknown")
    assert {r.criterion_id for r in v.results} == set(texts)


async def test_an_uncited_claim_is_sent_back_and_becomes_unknown_when_the_matcher_keeps_making_it(clean_db):
    ctx, fake, version = await _setup(clean_db)
    criteria = await trials.criteria(ctx, NCT)
    script(fake, answer_all(criteria, met=("EGFR",), fact=None))   # "met" with no Fact behind it

    await matching.rescan(ctx, version.id)

    matcher_calls = [c for c in fake.calls if c.lane == "deep"]
    assert len(matcher_calls) == ctx.settings.match_attempts
    assert "previous answer rejected because a met result must cite a Fact" in matcher_calls[1].user
    v = await matching.verdict(ctx, NCT, version.id)
    egfr = next(r for r in v.results if "EGFR" in next(c.text for c in criteria if c.id == r.criterion_id))
    assert egfr.outcome == "unknown" and egfr.citation is None
    assert egfr.rationale.startswith(f"unsupported after {ctx.settings.match_attempts} attempts:")
    assert v.degraded and v.unsupported_downgraded == 1


async def test_a_claim_the_evaluator_finds_unsupported_is_retried_and_accepted_once_fixed(clean_db):
    ctx, fake, version = await _setup(clean_db)
    criteria = await trials.criteria(ctx, NCT)
    sex = version.current()["sex assigned at birth"]
    activity = version.current()["daily activity"]
    attempts = [answer_all(criteria, met=("ECOG",), fact=sex), answer_all(criteria, met=("ECOG",), fact=activity)]
    script(fake, lambda user: attempts.pop(0)(user),
           judge=lambda user: [{"criterion_id": line.split()[1], "supported": "Fully active" in line,
                                "reason": "sex says nothing about activity"}
                               for line in user.splitlines() if line.startswith("CLAIM ")])

    await matching.rescan(ctx, version.id)

    matcher_calls = [c for c in fake.calls if c.lane == "deep"]
    assert len(matcher_calls) == 2
    assert "sex says nothing about activity" in matcher_calls[1].user
    v = await matching.verdict(ctx, NCT, version.id)
    assert v.attempts == 2 and not v.degraded
    assert any(r.outcome == "met" and r.citation.fact_id == activity.id for r in v.results)


async def test_a_rescan_is_idempotent_the_second_run_judges_nothing_and_calls_no_model(clean_db):
    ctx, fake, version = await _setup(clean_db)
    criteria = await trials.criteria(ctx, NCT)
    script(fake, answer_all(criteria))
    await matching.rescan(ctx, version.id)
    calls = len(fake.calls)

    again = await matching.rescan(ctx, version.id)

    assert again.judged == () and again.planned == () and again.skipped_existing == (NCT,)
    assert len(fake.calls) == calls
    assert len(await matching.verdicts_for_version(ctx, version.id)) == 1


async def test_unknown_results_become_doctor_questions_naming_the_trials_they_would_unblock(clean_db):
    ctx, fake, version = await _setup(clean_db)
    criteria = await trials.criteria(ctx, NCT)
    script(fake, answer_all(criteria, met=("ECOG",), fact=version.current()["daily activity"]))
    await matching.rescan(ctx, version.id)

    questions = await matching.questions_for_version(ctx, version.id)

    unknown = [c for c in criteria if "ECOG" not in c.text]
    assert {q.criterion_id for q in questions} == {c.id for c in unknown}
    egfr = next(q for q in questions if "EGFR" in q.subject)
    assert egfr.unblocks == (NCT,) and "patient's records" in egfr.text
    assert len((await matching.verdict(ctx, NCT, version.id)).questions) == len(unknown)


def study(nct, *, inclusion, exclusion=(), status="RECRUITING"):
    """A bare ClinicalTrials.gov v2 study with just the fields the loader reads."""
    text = "Inclusion Criteria:\n\n" + "\n".join(f"* {c}" for c in inclusion)
    if exclusion:
        text += "\n\nExclusion Criteria:\n\n" + "\n".join(f"* {c}" for c in exclusion)
    return {"protocolSection": {
        "identificationModule": {"nctId": nct, "briefTitle": f"Synthetic trial {nct}"},
        "statusModule": {"overallStatus": status, "lastUpdatePostDateStruct": {"date": "2026-10-01"}},
        "conditionsModule": {"conditions": ["Non-Small Cell Lung Cancer"]},
        "eligibilityModule": {"eligibilityCriteria": text}}}


def write_snapshot(tmp_path, studies):
    (tmp_path / "NCT07680790.json").write_text((SNAPSHOT / "NCT07680790.json").read_text())
    for s in studies:
        (tmp_path / f"{s['protocolSection']['identificationModule']['nctId']}.json").write_text(json.dumps(s))
    return tmp_path


async def test_verdicts_are_ranked_eligible_then_possible_by_fewest_unknowns_then_excluded(clean_db, tmp_path):
    snapshot = write_snapshot(tmp_path, [
        study("NCT00000001", inclusion=["Female participants"], exclusion=["Fully active patients"]),  # excluded
        study("NCT00000002", inclusion=["ECOG Performance Status 0-1"]),                                # eligible
        study("NCT00000003", inclusion=["ECOG Performance Status 0-1", "Measurable disease"]),          # 1 unknown
        study("NCT00000004", inclusion=["Closed trial"], status="COMPLETED"),                           # not judged
    ])
    ctx, fake, version = await _setup(clean_db, snapshot=snapshot)
    facts = version.current()

    def matcher(user):
        ids = [line.split()[1] for line in user.splitlines() if line.startswith("- NCT")]
        texts = {line.split()[1]: line for line in user.splitlines() if line.startswith("- NCT")}
        out = []
        for c in ids:
            if "ECOG" in texts[c] or "Fully active" in texts[c]:
                out.append({"criterion_id": c, "outcome": "met", "fact_id": facts["daily activity"].id, "rationale": "x"})
            elif "Female" in texts[c]:
                out.append({"criterion_id": c, "outcome": "met", "fact_id": facts["sex assigned at birth"].id,
                            "rationale": "x"})
            else:
                out.append({"criterion_id": c, "outcome": "unknown", "fact_id": None, "rationale": "x"})
        return out
    script(fake, matcher)

    report = await matching.rescan(ctx, version.id)

    assert "NCT00000004" not in report.planned
    ranked = await matching.verdicts_for_version(ctx, version.id)
    assert [(v.nct_id, v.outcome) for v in ranked] == [
        ("NCT00000002", "eligible"), ("NCT00000003", "possible"), (NCT, "possible"), ("NCT00000001", "excluded")]


async def test_a_verdict_on_one_trial_leaves_the_patients_verdict_on_another_trial_open(clean_db, tmp_path):
    snapshot = write_snapshot(tmp_path, [study("NCT00000002", inclusion=["ECOG Performance Status 0-1"])])
    ctx, fake, version = await _setup(clean_db, snapshot=snapshot)
    script(fake, lambda user: [{"criterion_id": line.split()[1], "outcome": "unknown", "fact_id": None, "rationale": "x"}
                               for line in user.splitlines() if line.startswith("- NCT")])

    await matching.rescan(ctx, version.id)

    from app.worldmodel import timeline
    open_edges = ctx.wm.edges_from(timeline.patient_entity_id(version.patient_id), via="verdict")
    assert sorted(e.to_id for e in open_edges) == ["trial:NCT00000002", f"trial:{NCT}"]


async def test_the_matcher_sees_criteria_and_cited_facts_with_age_worked_out_today_but_never_the_postcode(clean_db):
    ctx, fake, version = await _setup(clean_db)
    criteria = await trials.criteria(ctx, NCT)
    script(fake, answer_all(criteria))

    await matching.rescan(ctx, version.id)

    prompt = next(c for c in fake.calls if c.lane == "deep").user
    assert all(c.id in prompt for c in criteria)
    assert version.current()["daily activity"].id in prompt
    assert "Patient-reported, intake questionnaire, Q13" in prompt
    assert "68 years old" in prompt          # born March 1958, matched on 24 October 2026
    assert "2031" not in "".join(c.system + c.user for c in fake.calls)


async def test_change_between_versions_names_the_criteria_whose_result_moved_and_why(clean_db):
    ctx, fake, v1 = await _setup(clean_db)
    criteria = await trials.criteria(ctx, NCT)
    script(fake, answer_all(criteria))
    await matching.rescan(ctx, v1.id)
    changed = await record.submit_questionnaire(ctx, v1.patient_id, {**ANSWERS, "daily_activity": "light_activity"},
                                                respondent="other")
    v2 = await record.profile_version(ctx, changed.version.id)
    script(fake, answer_all(criteria, met=("ECOG",), fact=v2.current()["daily activity"]))
    await matching.rescan(ctx, v2.id)

    change = await matching.change_between(ctx, NCT, v1.id, v2.id)

    assert (change.outcome_from, change.outcome_to) == ("possible", "possible")
    [moved] = change.criteria_changed
    assert "ECOG" in moved.text and (moved.outcome_from, moved.outcome_to) == ("unknown", "met")
    assert moved.citation.fact_id == v2.current()["daily activity"].id


async def test_a_rescan_writes_its_start_each_trial_verdict_and_its_end_to_the_log_file(clean_db, tmp_path):
    from app import logfile
    ctx, fake, version = await _setup(clean_db)
    script(fake, answer_all(await trials.criteria(ctx, NCT)))
    path = tmp_path / "trialmatch.jsonl"
    logfile.configure(path)
    try:
        report = await matching.rescan(ctx, version.id)
    finally:
        logfile.reset()

    steps = [json.loads(x) for x in path.read_text().splitlines()]
    names = [s["step"] for s in steps if s["step"].startswith("matching.")]
    assert names == ["matching.rescan.started", "matching.trial_judged", "matching.rescan.finished"]
    started, judged, finished = (next(s for s in steps if s["step"] == n) for n in names)
    assert started["run_id"] == report.run_id and started["profile_version_id"] == version.id
    assert started["to_judge"] == [NCT]
    assert judged["nct_id"] == NCT and judged["outcome"] == "possible" and judged["run_id"] == report.run_id
    assert finished["judged"] == [NCT] and finished["failed"] == []
    assert any(s["step"] == "llm.complete" and s["run_id"] == report.run_id for s in steps)
