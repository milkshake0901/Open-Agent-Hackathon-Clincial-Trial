"""Seam 2 (spec #5): the matching facade, driven by the Diagnosis check (#14, #33, ADR 0005). The Condition labels the
Respondent ticks select which Trials a Re-scan judges and lists; "not sure" raises a Doctor question for the diagnosis
that belongs to no Criterion or Trial. Scripted fake model throughout."""
from __future__ import annotations

import json

from app import matching, record, trials
from app.llm.nightshift import FakeLLM
from tests.matching.test_rescan import NCT, study, write_snapshot
from tests.trials.test_ingest import AU, save_pages, study as saved_study

BREAST = "NCT00000009"
DIAGNOSIS = "lung cancer, the non small cell kind"
LUNG = ["Non-Small Cell Lung Cancer"]
HER2 = ["HER2-positive Breast Cancer"]


def breast_trial():
    s = study(BREAST, inclusion=["ECOG Performance Status 0-1"])
    s["protocolSection"]["conditionsModule"]["conditions"] = ["Breast Cancer", "HER2-positive Breast Cancer"]
    return s


def fake_model(picks, subject="lung cancer", diagnosis=DIAGNOSIS):
    """Intake drafts the diagnosis Fact; a Diagnosis check searches "cancer" and picks `picks`; the Matcher answers
    every Criterion unknown; the Evaluator has nothing to check."""
    def respond(lane, system, user):
        if lane == "fast" and "search phrases" in system:
            return {"phrases": ["cancer", "anterior cruciate ligament", "cruciate ligament"]}
        if lane == "fast" and "shortlist" in system:
            return {"labels": picks}
        if lane == "fast":
            return {"facts": [{"resource": "Condition", "subject": subject, "value": "non-small cell",
                               "observed_on": "2026-10-24", "page": 2, "quote": diagnosis, "question": "Q6"}]}
        if lane == "deep":
            return {"results": [{"criterion_id": line.split()[1], "outcome": "unknown", "fact_id": None,
                                 "rationale": "not stated"}
                                for line in user.splitlines() if line.startswith("- NCT")]}
        return {"checks": []}
    return FakeLLM(respond)


async def _setup(clean_db, tmp_path, picks=LUNG + HER2):
    from tests.conftest import make_ctx
    fake = fake_model(picks)
    ctx = make_ctx(clean_db, fake)
    await trials.load_snapshot(ctx, write_snapshot(tmp_path, [breast_trial()]))
    patient = await record.create_patient(ctx, "Demo patient S")
    outcome = await record.submit_questionnaire(ctx, patient, {"diagnosis": DIAGNOSIS, "birth_month": "1958-03"},
                                                "patient")
    return ctx, fake, patient, outcome.version


def judged_trials(fake):
    return {line.split()[1].split(":")[0] for c in fake.calls if c.lane == "deep"
            for line in c.user.splitlines() if line.startswith("- NCT")}


async def _tick(ctx, patient, labels, text=None):
    check = await record.check_diagnosis(ctx, patient, text)
    return await record.answer_diagnosis_check(ctx, patient, check.id, "ticked", labels=tuple(labels))


async def test_ticked_labels_select_the_trials_listing_them(clean_db, tmp_path):
    ctx, fake, patient, version = await _setup(clean_db, tmp_path)
    await _tick(ctx, patient, LUNG)

    report = await matching.rescan(ctx, version.id)

    assert report.planned == (NCT,) and judged_trials(fake) == {NCT}
    assert [v.nct_id for v in await matching.verdicts_for_version(ctx, version.id)] == [NCT]
    assert {q.nct_id for q in await matching.questions_for_version(ctx, version.id)} == {NCT}


async def test_verdicts_judged_under_an_earlier_choice_are_listed_only_for_trials_the_new_one_selects(clean_db, tmp_path):
    ctx, fake, patient, version = await _setup(clean_db, tmp_path)
    await _tick(ctx, patient, LUNG + HER2)
    await matching.rescan(ctx, version.id)
    assert judged_trials(fake) == {NCT, BREAST}

    await _tick(ctx, patient, HER2, "her2 breast cancer")

    assert [v.nct_id for v in await matching.verdicts_for_version(ctx, version.id)] == [BREAST]
    assert {q.nct_id for q in await matching.questions_for_version(ctx, version.id)} == {BREAST}


async def test_changing_the_ticked_labels_hides_the_verdicts_the_new_choice_does_not_select(clean_db, tmp_path):
    ctx, fake, patient, version = await _setup(clean_db, tmp_path)
    await _tick(ctx, patient, LUNG)
    await matching.rescan(ctx, version.id)
    assert [v.nct_id for v in await matching.verdicts_for_version(ctx, version.id)] == [NCT]

    await _tick(ctx, patient, HER2, "her2 breast cancer")
    report = await matching.rescan(ctx, version.id)

    assert report.planned == (BREAST,)
    assert [v.nct_id for v in await matching.verdicts_for_version(ctx, version.id)] == [BREAST]
    assert {q.nct_id for q in await matching.questions_for_version(ctx, version.id)} == {BREAST}


async def test_without_a_condition_term_a_rescan_judges_nothing_and_calls_no_model(clean_db, tmp_path):
    ctx, fake, patient, version = await _setup(clean_db, tmp_path)
    calls = len(fake.calls)

    report = await matching.rescan(ctx, version.id)

    assert report.planned == () and report.judged == () and report.skipped_existing == ()
    assert fake.calls[calls:] == []
    assert await matching.verdicts_for_version(ctx, version.id) == []
    assert await matching.questions_for_version(ctx, version.id) == []


async def test_none_of_these_leaves_no_condition_term_so_nothing_is_judged(clean_db, tmp_path):
    ctx, fake, patient, version = await _setup(clean_db, tmp_path)
    check = await record.check_diagnosis(ctx, patient)
    await record.answer_diagnosis_check(ctx, patient, check.id, "none_of_these")
    calls = len(fake.calls)

    report = await matching.rescan(ctx, version.id)

    assert report.planned == () and fake.calls[calls:] == []
    assert await matching.questions_for_version(ctx, version.id) == []


async def test_not_sure_judges_nothing_and_raises_a_doctor_question_for_the_diagnosis_on_no_criterion(
        clean_db, tmp_path):
    ctx, fake, patient, version = await _setup(clean_db, tmp_path)
    check = await record.check_diagnosis(ctx, patient)
    await record.answer_diagnosis_check(ctx, patient, check.id, "not_sure")
    calls = len(fake.calls)
    report = await matching.rescan(ctx, version.id)
    assert report.planned == () and fake.calls[calls:] == []

    questions = await matching.questions_for_version(ctx, version.id)

    first = questions[0]
    assert first.criterion_id is None and first.nct_id is None and first.subject == "diagnosis"
    assert DIAGNOSIS in first.text
    assert questions == [first]
    assert await matching.respondent_questions_for_version(ctx, version.id) == []


async def test_a_rescan_without_a_condition_term_says_so_in_the_log_file(clean_db, tmp_path):
    from app import logfile
    ctx, _, patient, version = await _setup(clean_db, tmp_path)
    path = tmp_path / "trialmatch.jsonl"
    logfile.configure(path)
    try:
        report = await matching.rescan(ctx, version.id)
    finally:
        logfile.reset()

    steps = [json.loads(x) for x in path.read_text().splitlines()]
    names = [s["step"] for s in steps if s["step"].startswith("matching.")]
    assert names == ["matching.rescan.no_condition_term", "matching.rescan.started", "matching.rescan.finished"]
    [said] = [s for s in steps if s["step"] == "matching.rescan.no_condition_term"]
    assert said["run_id"] == report.run_id and said["profile_version_id"] == version.id
    assert not any(s["step"] == "llm.complete" for s in steps)


async def test_when_no_label_fits_not_sure_raises_the_diagnosis_doctor_question_too(clean_db, tmp_path):
    ctx, _, patient, version = await _setup(clean_db, tmp_path, picks=[])
    check = await record.check_diagnosis(ctx, patient)
    assert check.shortlist == ()
    await record.answer_diagnosis_check(ctx, patient, check.id, "not_sure")

    questions = await matching.questions_for_version(ctx, version.id)

    assert [q.subject for q in questions if q.criterion_id is None] == ["diagnosis"]


ACL_LABELS = ["Anterior Cruciate Ligament Rupture", "Anterior Cruciate Ligament Injury"]


async def test_torn_acl_offers_the_acl_labels_and_ticking_them_selects_only_the_acl_trials(clean_db, tmp_path):
    """The original failure (#31): no ACL Trial says "tear", so a model-named term selected nothing."""
    from tests.conftest import make_ctx
    fake = fake_model(ACL_LABELS + ["Knee Osteoarthritis"], subject="anterior cruciate ligament tear",
                      diagnosis="Torn ACL")
    ctx = make_ctx(clean_db, fake)
    await trials.ingest(ctx, save_pages(tmp_path, [
        saved_study("NCT00000101", sites=[AU], conditions=("Anterior Cruciate Ligament Rupture",)),
        saved_study("NCT00000102", sites=[AU], conditions=("Anterior Cruciate Ligament Injury",)),
        saved_study("NCT00000103", sites=[AU], conditions=("Type 1 Diabetes",))]))
    patient = await record.create_patient(ctx, "Demo patient K")
    version = (await record.submit_questionnaire(ctx, patient, {"diagnosis": "Torn ACL", "birth_month": "2000-03"},
                                                 "patient")).version

    check = await record.check_diagnosis(ctx, patient)
    assert [one.label for one in check.shortlist] == ACL_LABELS
    assert "Torn ACL" in fake.calls[-2].user and "Type 1 Diabetes" not in fake.calls[-1].user
    await record.answer_diagnosis_check(ctx, patient, check.id, "ticked", labels=tuple(ACL_LABELS))
    report = await matching.rescan(ctx, version.id)

    assert set(report.planned) == {"NCT00000101", "NCT00000102"}
    assert judged_trials(fake) == {"NCT00000101", "NCT00000102"}
    assert {v.nct_id for v in await matching.verdicts_for_version(ctx, version.id)} == {"NCT00000101", "NCT00000102"}


async def test_when_the_diagnosis_goes_to_the_doctor_the_respondent_is_asked_nothing_until_it_is_settled(
        clean_db, tmp_path):
    ctx, fake, patient, version = await _setup(clean_db, tmp_path)
    respond = fake.responder

    def ask_again(lane, system, user):       # the Matcher points the diagnosis Criteria back at Q6, the rest at Q8
        out = respond(lane, system, user)
        if lane == "deep":
            lines = [l for l in user.splitlines() if l.startswith("- NCT")]
            for r, line in zip(out["results"], lines):
                r["ask"] = "Q6" if "ECOG" not in line else "Q8"
        return out
    fake.responder = ask_again
    await _tick(ctx, patient, LUNG + HER2)
    await matching.rescan(ctx, version.id)
    assert "Q6" in {q.question for q in await matching.respondent_questions_for_version(ctx, version.id)}

    check = await record.check_diagnosis(ctx, patient)
    await record.answer_diagnosis_check(ctx, patient, check.id, "not_sure")

    doctor = await matching.questions_for_version(ctx, version.id)
    assert doctor[0].subject == "diagnosis"
    assert await matching.respondent_questions_for_version(ctx, version.id) == []


async def test_a_reply_in_another_shape_is_retried_not_taken_as_an_empty_shortlist(clean_db, tmp_path):
    """Seen live on 2026-10-25: Nightshift answered the phrases call with a cached reply to the old single-term
    prompt ({"term": ..., "confidence": ...}), and the shortlist silently came back empty."""
    from tests.conftest import make_ctx
    fake = fake_model(ACL_LABELS, subject="anterior cruciate ligament tear", diagnosis="Torn ACL")
    respond, stale = fake.responder, {"left": 1}

    def cached_first(lane, system, user):
        if lane == "fast" and ("search phrases" in system or "shortlist" in system) and stale["left"]:
            stale["left"] -= 1
            return {"term": "anterior cruciate ligament tear", "confidence": 0.95}
        return respond(lane, system, user)
    fake.responder = cached_first
    ctx = make_ctx(clean_db, fake)
    await trials.ingest(ctx, save_pages(tmp_path, [
        saved_study("NCT00000101", sites=[AU], conditions=("Anterior Cruciate Ligament Rupture",)),
        saved_study("NCT00000102", sites=[AU], conditions=("Anterior Cruciate Ligament Injury",))]))
    patient = await record.create_patient(ctx, "Demo patient L")
    await record.submit_questionnaire(ctx, patient, {"diagnosis": "Torn ACL"}, "patient")

    check = await record.check_diagnosis(ctx, patient)

    assert [one.label for one in check.shortlist] == ACL_LABELS


async def test_each_shortlist_call_sends_a_user_message_no_other_prompt_sends(clean_db, tmp_path):
    """The runtime can answer a repeated user message from its cache whatever the system prompt says, so the two
    shortlist calls never reuse the bare diagnosis words as their whole user message."""
    from tests.conftest import make_ctx
    fake = fake_model(ACL_LABELS, subject="anterior cruciate ligament tear", diagnosis="Torn ACL")
    ctx = make_ctx(clean_db, fake)
    await trials.ingest(ctx, save_pages(tmp_path, [
        saved_study("NCT00000101", sites=[AU], conditions=("Anterior Cruciate Ligament Rupture",))]))
    patient = await record.create_patient(ctx, "Demo patient M")
    await record.submit_questionnaire(ctx, patient, {"diagnosis": "Torn ACL"}, "patient")

    await record.check_diagnosis(ctx, patient)

    phrases, pick = fake.calls[-2].user, fake.calls[-1].user
    assert phrases != "Diagnosis, in the Respondent's words:\nTorn ACL"
    assert phrases.startswith("Search phrases") and pick.startswith("Shortlist")
