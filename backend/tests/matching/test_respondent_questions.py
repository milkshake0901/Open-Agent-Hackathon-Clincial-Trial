"""Seam 2 (spec #5): the matching facade, for Respondent questions (#15). An unknown result that turns on something
the Respondent could know (a date, a medicine name) becomes a Respondent question pointing back at a questionnaire
question; anything needing clinical records stays a Doctor question. Exactly one of the two per unknown.
Trials are synthetic snapshot studies; the Matcher and Intake agent are a scripted fake model."""
from __future__ import annotations

from app import matching, record, trials
from tests.matching.test_rescan import ANSWERS, _setup, script, study, write_snapshot

WASHOUT = "No chemotherapy within 4 weeks before the first dose"
LAB = "Haemoglobin at least 9 g/dL"
VAGUE = {**ANSWERS, "treatments": "Had chemo, finished sometime recently"}


def intake(facts):
    """Script the Intake agent (fast lane) with one Fact list per call."""
    def respond(lane, system, user):
        return {"facts": facts}
    return respond


def chemo_fact(quote, observed_on):
    return {"resource": "Procedure", "subject": "chemotherapy", "value": "ended", "observed_on": observed_on,
            "page": 3, "quote": quote, "question": "Q8"}


def matcher(rule):
    """`rule(criterion_line, facts_text)` → (outcome, fact_id or None, ask or None) for each Criterion."""
    def answer(user):
        lines = user.splitlines()
        out = []
        for line in (l for l in lines if l.startswith("- NCT")):
            outcome, fact_id, ask = rule(line, lines)
            out.append({"criterion_id": line.split()[1], "outcome": outcome, "fact_id": fact_id, "rationale": "x",
                        "ask": ask})
        return out
    return answer


def fact_id(lines, subject):
    return next((l.split()[1] for l in lines if l.startswith("- fact:") and f"| {subject}:" in l), None)


def washout_rule(line, lines):
    """Vague chemo end date → unknown, ask the Respondent Q8; a precise one → met (chemo 24 days ago).
    The lab is never in the questionnaire, so it is unknown for the doctor."""
    if WASHOUT in line:
        precise = next((l for l in lines if "| chemotherapy:" in l and "recently" not in l), None)
        return ("met", fact_id(lines, "chemotherapy"), None) if precise else ("unknown", None, "Q8")
    return "unknown", None, None


async def _setup_washout(clean_db, tmp_path, answers=VAGUE):
    snapshot = write_snapshot(tmp_path, [study("NCT00000005", inclusion=[LAB], exclusion=[WASHOUT])])
    return await _setup_with_intake(clean_db, snapshot, answers,
                                    [chemo_fact("Had chemo, finished sometime recently", "2026")])


async def _setup_with_intake(clean_db, snapshot, answers, facts):
    from app.llm.nightshift import FakeLLM
    from tests.conftest import make_ctx
    fake = FakeLLM(intake(facts))
    ctx = make_ctx(clean_db, fake)
    await trials.load_snapshot(ctx, snapshot)
    patient = await record.create_patient(ctx, "Demo patient R")
    outcome = await record.submit_questionnaire(ctx, patient, answers, respondent="patient")
    assert isinstance(outcome, record.Committed)
    return ctx, fake, await record.profile_version(ctx, outcome.version.id)


async def test_a_vague_reported_date_near_a_washout_raises_a_respondent_question_not_a_doctor_question(clean_db,
                                                                                                         tmp_path):
    ctx, fake, version = await _setup_washout(clean_db, tmp_path)
    criteria = {c.text: c for c in await trials.criteria(ctx, "NCT00000005")}
    script(fake, matcher(washout_rule))

    await matching.rescan(ctx, version.id, only={"NCT00000005"})

    v = await matching.verdict(ctx, "NCT00000005", version.id)
    washout = next(r for r in v.results if r.criterion_id == criteria[WASHOUT].id)
    assert washout.outcome == "unknown"
    [asked] = v.respondent_questions
    assert (asked.criterion_id, asked.question, asked.question_id) == (criteria[WASHOUT].id, "Q8", "treatments")
    assert "What treatments have you had" in asked.subject
    assert {q.criterion_id for q in v.questions} == {criteria[LAB].id}   # the lab stays with the doctor


async def test_a_missing_lab_value_still_gives_a_doctor_question_even_if_the_matcher_points_at_the_questionnaire(
        clean_db, tmp_path):
    ctx, fake, version = await _setup_washout(clean_db, tmp_path)
    criteria = {c.text: c for c in await trials.criteria(ctx, "NCT00000005")}
    # labs are never asked in the questionnaire: Q4 is the postcode, Q99 does not exist
    script(fake, matcher(lambda line, lines: ("unknown", None, "Q4" if LAB in line else "Q99")))

    await matching.rescan(ctx, version.id, only={"NCT00000005"})

    v = await matching.verdict(ctx, "NCT00000005", version.id)
    assert v.respondent_questions == ()
    assert {q.criterion_id for q in v.questions} == {criteria[LAB].id, criteria[WASHOUT].id}
    prompt = next(c for c in fake.calls if c.lane == "deep").user
    assert "- Q8 What treatments have you had" in prompt and "- Q4 " not in prompt


async def test_respondent_questions_for_a_version_are_deduplicated_by_subject_with_the_trials_they_would_unblock(
        clean_db, tmp_path):
    other_washout = "No systemic anticancer therapy in the last 21 days"
    snapshot = write_snapshot(tmp_path, [
        study("NCT00000005", inclusion=[LAB], exclusion=[WASHOUT]),
        study("NCT00000006", inclusion=["Taking no anticoagulant medicine"], exclusion=[other_washout])])
    ctx, fake, version = await _setup_with_intake(clean_db, snapshot, VAGUE,
                                                  [chemo_fact("Had chemo, finished sometime recently", "2026")])

    def rule(line, lines):
        if WASHOUT in line or other_washout in line:
            return "unknown", None, "Q8"
        if "anticoagulant" in line:
            return "unknown", None, "Q9"     # medicines were not answered at all
        return "unknown", None, None
    script(fake, matcher(rule))
    await matching.rescan(ctx, version.id, only={"NCT00000005", "NCT00000006"})

    asked = await matching.respondent_questions_for_version(ctx, version.id)

    assert [(q.question, q.unblocks) for q in asked] == [
        ("Q8", ("NCT00000005", "NCT00000006")), ("Q9", ("NCT00000006",))]
    assert asked[0].nct_id == "NCT00000005" and WASHOUT in asked[0].text
    doctor = await matching.questions_for_version(ctx, version.id)
    assert [q.subject for q in doctor] == [LAB]


async def test_answering_a_respondent_question_makes_a_new_version_whose_verdict_moves(clean_db, tmp_path):
    ctx, fake, v1 = await _setup_washout(clean_db, tmp_path)
    script(fake, matcher(washout_rule))
    await matching.rescan(ctx, v1.id, only={"NCT00000005"})
    [asked] = await matching.respondent_questions_for_version(ctx, v1.id)

    # the Respondent answers Q8 again, exactly; the Intake agent reads the new words
    precise = "Last chemo was on 30 September 2026"
    matching_model = fake.responder
    fake.responder = lambda lane, system, user: (
        {"facts": [chemo_fact(precise, "2026-09-30")]} if lane == "fast" else matching_model(lane, system, user))
    resubmitted = await record.submit_questionnaire(ctx, v1.patient_id, {**VAGUE, asked.question_id: precise},
                                                    respondent="patient")
    assert isinstance(resubmitted, record.Committed)
    v2 = resubmitted.version
    await matching.rescan(ctx, v2.id, only={"NCT00000005"})

    assert v2.number == v1.number + 1
    change = await matching.change_between(ctx, "NCT00000005", v1.id, v2.id)
    assert (change.outcome_from, change.outcome_to) == ("possible", "excluded")
    [moved] = change.criteria_changed
    assert WASHOUT in moved.text and (moved.outcome_from, moved.outcome_to) == ("unknown", "met")
    assert moved.citation.quote == precise and moved.citation.question == "Q8"
    assert await matching.respondent_questions_for_version(ctx, v2.id) == []


async def test_a_clarified_date_earlier_than_the_vague_estimate_supersedes_it_and_moves_the_verdict(clean_db,
                                                                                                       tmp_path):
    # "around October 2026" is estimated as 15 October; the clarification says 2 October, which is EARLIER. A later
    # submission corrects an earlier one (ADR 0002 amendment), so the clarified Fact is current all the same.
    vague = "Chemo ended around October 2026"
    snapshot = write_snapshot(tmp_path, [study("NCT00000005", inclusion=[LAB], exclusion=[WASHOUT])])
    ctx, fake, v1 = await _setup_with_intake(clean_db, snapshot, {**ANSWERS, "treatments": vague},
                                             [chemo_fact(vague, "2026-10")])

    def rule(line, lines):
        if WASHOUT in line:
            precise = next((l for l in lines if "| chemotherapy:" in l and "around" not in l), None)
            return ("met", fact_id(lines, "chemotherapy"), None) if precise else ("unknown", None, "Q8")
        return "unknown", None, None
    script(fake, matcher(rule))
    await matching.rescan(ctx, v1.id, only={"NCT00000005"})

    precise = "Last chemo was on 2 October 2026"
    matching_model = fake.responder
    fake.responder = lambda lane, system, user: (
        {"facts": [chemo_fact(precise, "2026-10-02")]} if lane == "fast" else matching_model(lane, system, user))
    resubmitted = await record.submit_questionnaire(ctx, v1.patient_id, {**ANSWERS, "treatments": precise},
                                                    respondent="patient")
    assert isinstance(resubmitted, record.Committed)
    v2 = await record.profile_version(ctx, resubmitted.version.id)
    assert v2.current()["chemotherapy"].quote == precise
    await matching.rescan(ctx, v2.id, only={"NCT00000005"})

    change = await matching.change_between(ctx, "NCT00000005", v1.id, v2.id)
    assert (change.outcome_from, change.outcome_to) == ("possible", "excluded")
