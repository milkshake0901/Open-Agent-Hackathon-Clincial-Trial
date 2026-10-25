"""Seam 1 (spec #5): the record facade, for the Diagnosis check (#14, #33, ADR 0005). A model (scripted fake) turns the
free-text diagnosis into search phrases, code finds the Condition labels stored Trials use, and the model picks a
shortlist; the Respondent ticks labels, answers none of these (optionally re-wording) or not sure. Observed through
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

    answered = await record.answer_diagnosis_check(ctx, patient, check.id, "ticked",
                                                   labels=["non-small cell lung CANCER"])

    assert answered.status == "ticked" and answered.condition_term == ("Non-Small Cell Lung Cancer",)
    held = await record.diagnosis(ctx, patient)
    assert held.condition_term == ("Non-Small Cell Lung Cancer",) and held.shortlist == check.shortlist
    facts = (await record.profile_version(ctx, version.id)).facts
    assert [f.quote for f in facts if f.subject == "lung cancer"] == [DIAGNOSIS]


async def test_ticking_a_label_outside_the_shortlist_or_none_at_all_is_refused(clean_db, tmp_path):
    ctx, _, patient, _ = await _submitted(clean_db, tmp_path, NSCLC)
    check = await record.check_diagnosis(ctx, patient)

    with pytest.raises(record.InvalidAnswers):
        await record.answer_diagnosis_check(ctx, patient, check.id, "ticked", labels=["Breast Cancer"])
    with pytest.raises(record.InvalidAnswers):
        await record.answer_diagnosis_check(ctx, patient, check.id, "ticked", labels=[])
    assert await record.diagnosis(ctx, patient) is None
    await record.answer_diagnosis_check(ctx, patient, check.id, "ticked", labels=["Non-Small Cell Lung Cancer"])


async def test_none_of_these_with_new_words_starts_a_new_check(clean_db, tmp_path):
    ctx, fake, patient, _ = await _submitted(clean_db, tmp_path, (["lung"], ["Small Cell Lung Cancer"]), NSCLC)
    first = await record.check_diagnosis(ctx, patient)
    assert [one.label for one in first.shortlist] == ["Small Cell Lung Cancer"]

    second = await record.answer_diagnosis_check(ctx, patient, first.id, "none_of_these",
                                                 text="NSCLC, not the small cell type")

    assert "NSCLC, not the small cell type" in fake.calls[-2].user
    assert second.id != first.id and second.status == "proposed"
    assert second.text == "NSCLC, not the small cell type"
    assert [one.label for one in second.shortlist] == ["Non-Small Cell Lung Cancer", "Non-small Cell Lung Cancer Stage IV"]
    assert await record.diagnosis(ctx, patient) is None
    with pytest.raises(record.InvalidAnswers):           # the first check was answered: none of these
        await record.answer_diagnosis_check(ctx, patient, first.id, "ticked", labels=["Small Cell Lung Cancer"])
    await record.answer_diagnosis_check(ctx, patient, second.id, "ticked", labels=["Non-Small Cell Lung Cancer",
                                                                                  "Non-small Cell Lung Cancer Stage IV"])
    assert (await record.diagnosis(ctx, patient)).condition_term == ("Non-Small Cell Lung Cancer",
                                                                     "Non-small Cell Lung Cancer Stage IV")


async def test_none_of_these_without_new_words_asks_again_and_settles_nothing(clean_db, tmp_path):
    ctx, _, patient, _ = await _submitted(clean_db, tmp_path, NSCLC)
    check = await record.check_diagnosis(ctx, patient)

    rejected = await record.answer_diagnosis_check(ctx, patient, check.id, "none_of_these")

    assert rejected.status == "none_of_these" and rejected.ask_again and rejected.condition_term is None
    assert await record.diagnosis(ctx, patient) is None


async def test_not_sure_says_check_with_the_gp_and_holds_no_condition_term(clean_db, tmp_path):
    ctx, _, patient, _ = await _submitted(clean_db, tmp_path, NSCLC)
    check = await record.check_diagnosis(ctx, patient)

    unsure = await record.answer_diagnosis_check(ctx, patient, check.id, "not_sure")

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
        await record.answer_diagnosis_check(ctx, patient, check.id, "ticked", labels=["Breast Cancer"])
    assert (await record.answer_diagnosis_check(ctx, patient, check.id, "not_sure")).needs_gp


async def test_an_answer_is_given_once_and_only_to_the_patients_own_check(clean_db, tmp_path):
    ctx, _, patient, _ = await _submitted(clean_db, tmp_path, NSCLC)
    check = await record.check_diagnosis(ctx, patient)
    other = await record.create_patient(ctx, "Demo patient E")
    ticked = ["Non-Small Cell Lung Cancer"]

    with pytest.raises(record.NotFound):
        await record.answer_diagnosis_check(ctx, other, check.id, "ticked", labels=ticked)
    await record.answer_diagnosis_check(ctx, patient, check.id, "ticked", labels=ticked)
    with pytest.raises(record.InvalidAnswers):
        await record.answer_diagnosis_check(ctx, patient, check.id, "none_of_these")
    with pytest.raises(record.InvalidAnswers):
        await record.answer_diagnosis_check(ctx, patient, check.id, "maybe")


async def test_checking_before_any_diagnosis_answer_raises_not_found(clean_db):
    from tests.conftest import make_ctx
    fake = fake_model()
    ctx = make_ctx(clean_db, fake)
    patient = await record.create_patient(ctx, "Demo patient F")

    with pytest.raises(record.NotFound):
        await record.check_diagnosis(ctx, patient)
    assert fake.calls == []
