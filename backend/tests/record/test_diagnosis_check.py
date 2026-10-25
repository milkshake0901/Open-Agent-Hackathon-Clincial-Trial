"""Seam 1 (spec #5): the record facade, for the Diagnosis check (#14, #33, ADR 0005). A model (scripted fake) turns the
free-text diagnosis into search phrases, code finds the Condition labels stored Trials use, and the model picks a
shortlist; the Respondent ticks labels, answers none of these with the diagnosis in other words, or not sure. Observed through
check_diagnosis, answer_diagnosis_check, diagnosis and the prompts the fake captured."""
from __future__ import annotations

import pytest

from app import record, trials
from app.llm.nightshift import FakeLLM
from tests.trials.test_ingest import AU, save_pages, study

DIAGNOSIS = "lung cancer, the non small cell kind"
INTAKE_FACTS = [{"resource": "Condition", "subject": "lung cancer", "value": "non-small cell", "observed_on": "2026-10-24",
                 "page": 2, "quote": DIAGNOSIS, "question": "Q6"}]
PAGES = [
    study("NCT00000001", sites=[AU], conditions=("Non-Small Cell Lung Cancer",)),
    study("NCT00000002", sites=[AU], conditions=("Non-small Cell Lung Cancer Stage IV", "Small Cell Lung Cancer")),
    study("NCT00000003", status="COMPLETED", sites=[AU], primary_completion="2022-06",
          conditions=("non-small cell lung cancer",)),
    study("NCT00000004", sites=[AU], conditions=("Breast Cancer",))]


def fake_model(*rounds):
    """Intake answers with INTAKE_FACTS; each Diagnosis check takes the next (search phrases, picked labels)."""
    replies = list(rounds)
    current: list = []

    def respond(lane, system, user):
        if "search phrases" in system:
            current[:] = [replies.pop(0)]
            return {"phrases": current[0][0]}
        if "shortlist" in system:
            return {"labels": current[0][1]}
        return {"facts": INTAKE_FACTS}
    return FakeLLM(respond)


async def _submitted(clean_db, tmp_path, *rounds):
    from tests.conftest import make_ctx
    fake = fake_model(*rounds)
    ctx = make_ctx(clean_db, fake)
    await trials.ingest(ctx, save_pages(tmp_path, PAGES))
    patient = await record.create_patient(ctx, "Demo patient D")
    outcome = await record.submit_questionnaire(ctx, patient, {"diagnosis": DIAGNOSIS, "postcode": "2031"}, "patient")
    assert isinstance(outcome, record.Committed)
    return ctx, fake, patient, outcome.version


NSCLC = (["non-small cell lung cancer", "lung cancer"],
         ["Non-Small Cell Lung Cancer", "Non-small Cell Lung Cancer Stage IV", "Pancreatic Cancer"])


async def test_the_shortlist_holds_only_stored_labels_with_their_counts_and_the_model_sees_only_words_and_labels(
        clean_db, tmp_path):
    ctx, fake, patient, _ = await _submitted(clean_db, tmp_path, NSCLC)

    check = await record.check_diagnosis(ctx, patient)

    assert check.text == DIAGNOSIS and check.status == "proposed" and not check.needs_gp
    assert check.shortlist == (trials.ConditionLabel("Non-Small Cell Lung Cancer", open=1, closed=1),
                               trials.ConditionLabel("Non-small Cell Lung Cancer Stage IV", open=1, closed=0))
    phrases, pick = fake.calls[-2:]
    assert phrases.lane == pick.lane == "fast"
    assert DIAGNOSIS in phrases.user and "2031" not in phrases.user + pick.user
    assert "Small Cell Lung Cancer" in pick.user and "Breast Cancer" not in pick.user
    assert await record.diagnosis(ctx, patient) is None      # nothing holds until the Respondent answers


async def test_ticked_labels_become_the_condition_term_and_the_free_text_stays_the_quote(clean_db, tmp_path):
    ctx, _, patient, version = await _submitted(clean_db, tmp_path, NSCLC)
    check = await record.check_diagnosis(ctx, patient)

    answered = await record.answer_diagnosis_check(ctx, patient, check.id, record.Ticked(("non-small cell lung CANCER",)))

    assert answered.status == "ticked" and answered.condition_term == ("Non-Small Cell Lung Cancer",)
    held = await record.diagnosis(ctx, patient)
    assert held.condition_term == ("Non-Small Cell Lung Cancer",) and held.shortlist == check.shortlist
    facts = (await record.profile_version(ctx, version.id)).facts
    assert [f.quote for f in facts if f.subject == "lung cancer"] == [DIAGNOSIS]


async def test_ticking_a_label_outside_the_shortlist_or_none_at_all_is_refused(clean_db, tmp_path):
    ctx, _, patient, _ = await _submitted(clean_db, tmp_path, NSCLC)
    check = await record.check_diagnosis(ctx, patient)

    with pytest.raises(record.InvalidAnswers):
        await record.answer_diagnosis_check(ctx, patient, check.id, record.Ticked(("Breast Cancer",)))
    with pytest.raises(record.InvalidAnswers):
        await record.answer_diagnosis_check(ctx, patient, check.id, record.Ticked(()))
    assert await record.diagnosis(ctx, patient) is None
    await record.answer_diagnosis_check(ctx, patient, check.id, record.Ticked(("Non-Small Cell Lung Cancer",)))


async def test_none_of_these_with_new_words_starts_a_new_check(clean_db, tmp_path):
    ctx, fake, patient, _ = await _submitted(clean_db, tmp_path, (["lung"], ["Small Cell Lung Cancer"]), NSCLC)
    first = await record.check_diagnosis(ctx, patient)
    assert [one.label for one in first.shortlist] == ["Small Cell Lung Cancer"]

    second = await record.answer_diagnosis_check(ctx, patient, first.id, record.NoneOfThese("NSCLC, not the small cell type"))

    assert "NSCLC, not the small cell type" in fake.calls[-2].user
    assert second.id != first.id and second.status == "proposed"
    assert second.text == "NSCLC, not the small cell type"
    assert [one.label for one in second.shortlist] == ["Non-Small Cell Lung Cancer", "Non-small Cell Lung Cancer Stage IV"]
    assert await record.diagnosis(ctx, patient) is None
    with pytest.raises(record.InvalidAnswers):           # the first check was answered: none of these
        await record.answer_diagnosis_check(ctx, patient, first.id, record.Ticked(("Small Cell Lung Cancer",)))
    await record.answer_diagnosis_check(ctx, patient, second.id, record.Ticked(("Non-Small Cell Lung Cancer",
                                                                                  "Non-small Cell Lung Cancer Stage IV")))
    assert (await record.diagnosis(ctx, patient)).condition_term == ("Non-Small Cell Lung Cancer",
                                                                     "Non-small Cell Lung Cancer Stage IV")


async def test_none_of_these_needs_new_words_and_without_them_answers_nothing(clean_db, tmp_path):
    ctx, fake, patient, _ = await _submitted(clean_db, tmp_path, NSCLC)
    check = await record.check_diagnosis(ctx, patient)
    calls = len(fake.calls)

    for words in ("", "   "):
        with pytest.raises(record.InvalidAnswers):
            await record.answer_diagnosis_check(ctx, patient, check.id, record.NoneOfThese(words))

    assert fake.calls[calls:] == [] and await record.diagnosis(ctx, patient) is None
    assert (await record.answer_diagnosis_check(ctx, patient, check.id, record.NotSure())).needs_gp


async def test_not_sure_says_check_with_the_gp_and_holds_no_condition_term(clean_db, tmp_path):
    ctx, _, patient, _ = await _submitted(clean_db, tmp_path, NSCLC)
    check = await record.check_diagnosis(ctx, patient)

    unsure = await record.answer_diagnosis_check(ctx, patient, check.id, record.NotSure())

    assert unsure.status == "not_sure" and unsure.needs_gp and unsure.condition_term is None
    held = await record.diagnosis(ctx, patient)
    assert held.needs_gp and held.condition_term is None


async def test_when_no_label_fits_the_shortlist_is_empty_and_only_none_of_these_or_not_sure_can_answer(
        clean_db, tmp_path):
    ctx, fake, patient, _ = await _submitted(clean_db, tmp_path, (["glioblastoma"], []))

    check = await record.check_diagnosis(ctx, patient)

    assert check.shortlist == () and check.status == "proposed"
    assert not any("shortlist" in c.system for c in fake.calls)      # no candidates: no second call
    with pytest.raises(record.InvalidAnswers):
        await record.answer_diagnosis_check(ctx, patient, check.id, record.Ticked(("Breast Cancer",)))
    assert (await record.answer_diagnosis_check(ctx, patient, check.id, record.NotSure())).needs_gp


async def test_an_answer_is_given_once_and_only_to_the_patients_own_check(clean_db, tmp_path):
    ctx, _, patient, _ = await _submitted(clean_db, tmp_path, NSCLC)
    check = await record.check_diagnosis(ctx, patient)
    other = await record.create_patient(ctx, "Demo patient E")
    ticked = ("Non-Small Cell Lung Cancer",)

    with pytest.raises(record.NotFound):
        await record.answer_diagnosis_check(ctx, other, check.id, record.Ticked(ticked))
    await record.answer_diagnosis_check(ctx, patient, check.id, record.Ticked(ticked))
    with pytest.raises(record.AlreadyAnswered):
        await record.answer_diagnosis_check(ctx, patient, check.id, record.NotSure())


async def test_new_words_for_an_answered_check_are_refused_before_any_model_call(clean_db, tmp_path):
    ctx, fake, patient, _ = await _submitted(clean_db, tmp_path, NSCLC)
    check = await record.check_diagnosis(ctx, patient)
    await record.answer_diagnosis_check(ctx, patient, check.id, record.NotSure())
    fake.responder = None                                  # a model call would fail with LlmUnavailable
    calls = len(fake.calls)

    with pytest.raises(record.AlreadyAnswered):
        await record.answer_diagnosis_check(ctx, patient, check.id, record.NoneOfThese("NSCLC"))
    with pytest.raises(record.AlreadyAnswered):            # answered: not even its labels are looked at
        await record.answer_diagnosis_check(ctx, patient, check.id, record.Ticked(("Breast Cancer",)))
    assert fake.calls[calls:] == []


async def test_checking_before_any_diagnosis_answer_raises_not_found(clean_db):
    from tests.conftest import make_ctx
    fake = fake_model()
    ctx = make_ctx(clean_db, fake)
    patient = await record.create_patient(ctx, "Demo patient F")

    with pytest.raises(record.NotFound):
        await record.check_diagnosis(ctx, patient)
    assert fake.calls == []


REWORDED = "Mrs Jane Citizen here, call me on 0412 345 678: it is NSCLC"


async def test_names_and_phone_numbers_in_the_diagnosis_words_never_reach_the_model_the_check_or_the_log_file(
        clean_db, tmp_path):
    import json

    from app import logfile
    path = tmp_path / "trialmatch.jsonl"
    logfile.configure(path)
    try:
        ctx, fake, patient, _ = await _submitted(clean_db, tmp_path, NSCLC, NSCLC)
        first = await record.check_diagnosis(ctx, patient)
        second = await record.answer_diagnosis_check(ctx, patient, first.id, record.NoneOfThese(REWORDED))
    finally:
        logfile.reset()

    prompts = " ".join(c.user for c in fake.calls)
    assert "NSCLC" in prompts and "[PHONE]" in prompts
    for secret in ("Jane", "Citizen", "0412 345 678"):
        assert secret not in prompts
        assert secret not in second.text
        assert secret not in path.read_text()
    steps = [line["step"] for line in map(json.loads, path.read_text().splitlines())]
    assert steps.count("record.diagnosis_check.offered") == 2 and "record.diagnosis_check.answered" in steps


async def test_none_of_these_with_new_words_leaves_the_check_unanswered_when_the_model_is_unavailable(
        clean_db, tmp_path):
    from app.llm import LlmUnavailable
    ctx, fake, patient, _ = await _submitted(clean_db, tmp_path, NSCLC)
    check = await record.check_diagnosis(ctx, patient)
    fake.responder = None                                  # every later call fails

    with pytest.raises(LlmUnavailable):
        await record.answer_diagnosis_check(ctx, patient, check.id, record.NoneOfThese("NSCLC"))

    answered = await record.answer_diagnosis_check(ctx, patient, check.id, record.Ticked(("Non-Small Cell Lung Cancer",)))
    assert answered.condition_term == ("Non-Small Cell Lung Cancer",)


async def test_a_check_confirmed_before_condition_labels_settles_the_diagnosis_with_no_condition_term_or_gp_question(
        clean_db, tmp_path):
    """Migration 0006 leaves a check confirmed under the single-term design `confirmed`, with no ticked labels (spec #31:
    the Respondent redoes the step). It holds no Condition term, raises no Doctor question, and still outranks the
    checks settled before it."""
    from pathlib import Path
    ctx, _, patient, _ = await _submitted(clean_db, tmp_path, NSCLC)
    unsure = await record.check_diagnosis(ctx, patient)
    await record.answer_diagnosis_check(ctx, patient, unsure.id, record.NotSure())
    await clean_db.execute(
        "INSERT INTO diagnosis_check (id, patient_id, text, shortlist, ticked, status, created_at, answered_at, "
        "settled_seq) VALUES ('dx_legacy', $1, 'lung cancer', '[]', '[]', 'confirmed', now(), now(), "
        "nextval('diagnosis_check_settled'))", patient)

    def as_before(held):
        assert held.id == "dx_legacy" and held.condition_term is None and not held.needs_gp

    as_before(await record.diagnosis(ctx, patient))
    migration = (Path(__file__).resolve().parents[3] / "db" / "migrations" / "0006_diagnosis_shortlist.sql").read_text()
    for _ in range(2):                                     # safe to run twice
        await clean_db.execute(migration)
        assert await clean_db.fetchval("SELECT status FROM diagnosis_check WHERE id = 'dx_legacy'") == "confirmed"
        as_before(await record.diagnosis(ctx, patient))
    assert await clean_db.fetchval(f"SELECT status FROM diagnosis_check WHERE id = '{unsure.id}'") == "not_sure"
    with pytest.raises(record.AlreadyAnswered):
        await record.answer_diagnosis_check(ctx, patient, record.DiagnosisCheckId("dx_legacy"), record.NotSure())
