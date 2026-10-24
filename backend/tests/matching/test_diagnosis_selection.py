"""Seam 2 (spec #5): the matching facade, driven by the diagnosis check (#14). A confirmed condition term selects
which snapshot Trials a Re-scan judges and lists; "not sure" or an unclear proposal raises a Doctor question for the
diagnosis that belongs to no Criterion or Trial. Scripted fake model throughout."""
from __future__ import annotations

from app import matching, record, trials
from app.llm.nightshift import FakeLLM
from tests.matching.test_rescan import NCT, study, write_snapshot

BREAST = "NCT00000009"
DIAGNOSIS = "lung cancer, the non small cell kind"


def breast_trial():
    s = study(BREAST, inclusion=["ECOG Performance Status 0-1"])
    s["protocolSection"]["conditionsModule"]["conditions"] = ["Breast Cancer", "HER2-positive Breast Cancer"]
    return s


def fake_model(term, confidence=0.9):
    """Intake drafts the diagnosis Fact; the diagnosis check proposes `term`; the Matcher answers every Criterion
    unknown; the Evaluator has nothing to check."""
    def respond(lane, system, user):
        if lane == "fast" and "condition term" in system:
            return {"term": term, "confidence": confidence}
        if lane == "fast":
            return {"facts": [{"resource": "Condition", "subject": "lung cancer", "value": "non-small cell",
                               "observed_on": "2026-10-24", "page": 2, "quote": DIAGNOSIS, "question": "Q6"}]}
        if lane == "deep":
            return {"results": [{"criterion_id": line.split()[1], "outcome": "unknown", "fact_id": None,
                                 "rationale": "not stated"}
                                for line in user.splitlines() if line.startswith("- NCT")]}
        return {"checks": []}
    return FakeLLM(respond)


async def _setup(clean_db, tmp_path, term, confidence=0.9):
    from tests.conftest import make_ctx
    fake = fake_model(term, confidence)
    ctx = make_ctx(clean_db, fake)
    await trials.load_snapshot(ctx, write_snapshot(tmp_path, [breast_trial()]))
    patient = await record.create_patient(ctx, "Demo patient S")
    outcome = await record.submit_questionnaire(ctx, patient, {"diagnosis": DIAGNOSIS, "birth_month": "1958-03"},
                                                "patient")
    return ctx, fake, patient, outcome.version


def judged_trials(fake):
    return {line.split()[1].split(":")[0] for c in fake.calls if c.lane == "deep"
            for line in c.user.splitlines() if line.startswith("- NCT")}


async def test_a_confirmed_term_selects_the_trials_for_that_condition(clean_db, tmp_path):
    ctx, fake, patient, version = await _setup(clean_db, tmp_path, "non-small cell lung cancer")
    check = await record.check_diagnosis(ctx, patient)
    await record.answer_diagnosis_check(ctx, patient, check.id, "yes")

    report = await matching.rescan(ctx, version.id)

    assert report.planned == (NCT,) and judged_trials(fake) == {NCT}
    assert [v.nct_id for v in await matching.verdicts_for_version(ctx, version.id)] == [NCT]
    assert {q.nct_id for q in await matching.questions_for_version(ctx, version.id)} == {NCT}


async def test_verdicts_judged_before_the_term_was_confirmed_are_listed_only_for_selected_trials(clean_db, tmp_path):
    ctx, fake, patient, version = await _setup(clean_db, tmp_path, "HER2-positive breast cancer")
    await matching.rescan(ctx, version.id)
    assert judged_trials(fake) == {NCT, BREAST}

    check = await record.check_diagnosis(ctx, patient, "her2 breast cancer")
    await record.answer_diagnosis_check(ctx, patient, check.id, "yes")

    assert [v.nct_id for v in await matching.verdicts_for_version(ctx, version.id)] == [BREAST]
    assert {q.nct_id for q in await matching.questions_for_version(ctx, version.id)} == {BREAST}


async def test_without_a_settled_diagnosis_every_active_trial_is_judged(clean_db, tmp_path):
    ctx, fake, patient, version = await _setup(clean_db, tmp_path, "non-small cell lung cancer")
    check = await record.check_diagnosis(ctx, patient)
    await record.answer_diagnosis_check(ctx, patient, check.id, "no")

    report = await matching.rescan(ctx, version.id)

    assert set(report.planned) == {NCT, BREAST}
    assert not any(q.criterion_id is None for q in await matching.questions_for_version(ctx, version.id))


async def test_not_sure_raises_a_doctor_question_for_the_diagnosis_on_no_criterion(clean_db, tmp_path):
    ctx, _, patient, version = await _setup(clean_db, tmp_path, "non-small cell lung cancer")
    check = await record.check_diagnosis(ctx, patient)
    await record.answer_diagnosis_check(ctx, patient, check.id, "not_sure")
    report = await matching.rescan(ctx, version.id)
    assert set(report.planned) == {NCT, BREAST}

    questions = await matching.questions_for_version(ctx, version.id)

    first = questions[0]
    assert first.criterion_id is None and first.nct_id is None and first.subject == "diagnosis"
    assert DIAGNOSIS in first.text
    assert [q for q in questions if q.criterion_id is None] == [first]


async def test_an_unclear_proposal_raises_the_diagnosis_doctor_question_too(clean_db, tmp_path):
    ctx, _, patient, version = await _setup(clean_db, tmp_path, "lung neoplasm", confidence=0.2)
    await record.check_diagnosis(ctx, patient)

    questions = await matching.questions_for_version(ctx, version.id)

    assert [q.subject for q in questions if q.criterion_id is None] == ["diagnosis"]
