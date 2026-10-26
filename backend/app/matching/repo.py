"""app/matching/repo.py — SQL for verdict, criterion_result, doctor_question, respondent_question. Reads only."""
from __future__ import annotations

from app.matching.types import (
    Citation, CitedRegion, CriterionResult, DoctorQuestion, Outcome, RespondentQuestion, ValidatedResults, Verdict, VerdictOutcome,
)
from app.record import DocumentHash, FactId, ProfileVersionId
from app.sql.reader import SqlReader
from app.trace import RunId
from app.trials import CriterionId, NctId, Trial, active_filter, listing_filter, trial_columns, trial_from_row


async def trials_needing_verdict(reader: SqlReader, version_id: ProfileVersionId, label_keys: list[str],
                                 only: set[NctId] | None) -> tuple[list[Trial], list[NctId]]:
    """The idempotent plan, in one query (see loop.plan): active Trials listing a label with one of these keys
    (trials.label_keys), each with whether a Verdict exists for (Trial, its current eligibility hash, this version)."""
    rows = await reader.fetch(
        f"SELECT {trial_columns('t')}, v.nct_id AS judged FROM {reader.table('trial')} t "
        f"LEFT JOIN {reader.table('verdict')} v ON v.nct_id = t.nct_id AND v.eligibility_hash = t.eligibility_hash "
        f"AND v.profile_version_id = $1 WHERE {active_filter('t')} "
        f"AND {listing_filter(reader, label_keys, alias='t', start=2)} ORDER BY t.nct_id", (version_id, *label_keys))
    rows = [r for r in rows if only is None or r["nct_id"] in only]
    return ([trial_from_row(r) for r in rows if r["judged"] is None],
            [NctId(r["nct_id"]) for r in rows if r["judged"] is not None])


def _citation(r: dict) -> Citation | None:
    """A stored result's Citation: the Fact, its Document's filename, and for a letter Fact its Region's box."""
    if not r["fact_id"]:
        return None
    region = (CitedRegion(r["span_id"], r["x0"], r["y0"], r["x1"], r["y1"]) if r["span_id"] and r["x0"] is not None
              else None)
    return Citation(fact_id=FactId(r["fact_id"]), document_hash=DocumentHash(r["document_hash"]), page=r["page"],
                    quote=r["quote"], question=r["question"], filename=r["filename"], region=region)


async def _results(reader: SqlReader, key: tuple) -> ValidatedResults:
    rows = await reader.fetch(
        f"SELECT cr.criterion_id, cr.outcome, cr.rationale, cr.ask, f.id AS fact_id, f.document_hash, f.page, f.quote, "
        f"f.question, f.span_id, d.filename, s.x0, s.y0, s.x1, s.y1 FROM {reader.table('criterion_result')} cr "
        f"JOIN {reader.table('criterion')} c ON c.id = cr.criterion_id "
        f"LEFT JOIN {reader.table('fact')} f ON f.id = cr.fact_id "
        f"LEFT JOIN {reader.table('document')} d ON d.hash = f.document_hash "
        f"LEFT JOIN {reader.table('document_span')} s ON s.id = f.span_id "
        "WHERE cr.nct_id = $1 AND cr.eligibility_hash = $2 AND cr.profile_version_id = $3 ORDER BY c.ordinal", key)
    return ValidatedResults(CriterionResult(
        criterion_id=CriterionId(r["criterion_id"]), outcome=Outcome(r["outcome"]), rationale=r["rationale"], ask=r["ask"],
        citation=_citation(r)) for r in rows)


_DQ_COLS = "q.criterion_id, q.nct_id, q.subject, q.text"


def _doctor_question(r: dict) -> DoctorQuestion:
    return DoctorQuestion(criterion_id=CriterionId(r["criterion_id"]), nct_id=NctId(r["nct_id"]), subject=r["subject"],
                          text=r["text"])


async def _questions(reader: SqlReader, key: tuple) -> tuple[DoctorQuestion, ...]:
    rows = await reader.fetch(
        f"SELECT {_DQ_COLS} FROM {reader.table('doctor_question')} q "
        f"JOIN {reader.table('criterion')} c ON c.id = q.criterion_id "
        "WHERE q.nct_id = $1 AND q.eligibility_hash = $2 AND q.profile_version_id = $3 ORDER BY c.ordinal", key)
    return tuple(_doctor_question(r) for r in rows)


_RQ_COLS = "q.criterion_id, q.nct_id, q.question_id, q.question, q.subject, q.text"


def _respondent_question(r: dict) -> RespondentQuestion:
    return RespondentQuestion(criterion_id=CriterionId(r["criterion_id"]), nct_id=NctId(r["nct_id"]),
                              question_id=r["question_id"], question=r["question"], subject=r["subject"],
                              text=r["text"])


async def _respondent_questions(reader: SqlReader, key: tuple) -> tuple[RespondentQuestion, ...]:
    rows = await reader.fetch(
        f"SELECT {_RQ_COLS} FROM {reader.table('respondent_question')} q "
        f"JOIN {reader.table('criterion')} c ON c.id = q.criterion_id "
        "WHERE q.nct_id = $1 AND q.eligibility_hash = $2 AND q.profile_version_id = $3 ORDER BY c.ordinal", key)
    return tuple(_respondent_question(r) for r in rows)


async def _verdict(reader: SqlReader, r: dict, with_results: bool) -> Verdict:
    key = (r["nct_id"], r["eligibility_hash"], r["profile_version_id"])
    return Verdict(nct_id=NctId(r["nct_id"]), profile_version_id=ProfileVersionId(r["profile_version_id"]),
                   eligibility_hash=r["eligibility_hash"], outcome=VerdictOutcome(r["outcome"]),
                   results=await _results(reader, key) if with_results else ValidatedResults(),
                   questions=await _questions(reader, key) if with_results else (),
                   respondent_questions=await _respondent_questions(reader, key) if with_results else (),
                   run_id=RunId(r["run_id"]), attempts=r["attempts"],
                   unsupported_downgraded=r["unsupported_downgraded"], degraded=r["degraded"])


_VERDICT_COLS = ("v.nct_id, v.eligibility_hash, v.profile_version_id, v.outcome, v.run_id, v.attempts, "
                 "v.unsupported_downgraded, v.degraded")


def _current(reader: SqlReader) -> str:
    """Verdicts judged against each Trial's CURRENT Criteria (old-hash Verdicts stay stored, ADR 0002)."""
    return (f"FROM {reader.table('verdict')} v JOIN {reader.table('trial')} t "
            "ON t.nct_id = v.nct_id AND t.eligibility_hash = v.eligibility_hash")


async def verdict(reader: SqlReader, nct_id: NctId, version_id: ProfileVersionId, *, with_results: bool) -> Verdict | None:
    rows = await reader.fetch(f"SELECT {_VERDICT_COLS} {_current(reader)} "
                              "WHERE v.nct_id = $1 AND v.profile_version_id = $2", (nct_id, version_id))
    return await _verdict(reader, rows[0], with_results) if rows else None


async def verdicts_for_version(reader: SqlReader, version_id: ProfileVersionId) -> list[tuple[Verdict, int]]:
    """Each Verdict (results loaded) with its count of unknown results, unranked; none for a dropped Trial (its
    Verdicts stay stored as history, ADR 0002)."""
    rows = await reader.fetch(
        f"SELECT {_VERDICT_COLS}, (SELECT count(*) FROM {reader.table('criterion_result')} cr "
        "WHERE cr.nct_id = v.nct_id AND cr.eligibility_hash = v.eligibility_hash "
        "AND cr.profile_version_id = v.profile_version_id AND cr.outcome = 'unknown') AS unknowns "
        f"{_current(reader)} WHERE v.profile_version_id = $1 AND NOT t.dropped ORDER BY v.nct_id", (version_id,))
    return [(await _verdict(reader, r, True), int(r["unknowns"])) for r in rows]


async def questions_for_version(reader: SqlReader, version_id: ProfileVersionId) -> list[DoctorQuestion]:
    """Every Doctor question of the version's current Verdicts on Trials not dropped, in Trial then Criterion order
    (not deduplicated)."""
    rows = await reader.fetch(
        f"SELECT {_DQ_COLS} FROM {reader.table('doctor_question')} q "
        f"JOIN {reader.table('trial')} t ON t.nct_id = q.nct_id AND t.eligibility_hash = q.eligibility_hash "
        f"JOIN {reader.table('criterion')} c ON c.id = q.criterion_id "
        "WHERE q.profile_version_id = $1 AND NOT t.dropped ORDER BY q.nct_id, c.ordinal", (version_id,))
    return [_doctor_question(r) for r in rows]


async def respondent_questions_for_version(reader: SqlReader, version_id: ProfileVersionId) -> list[RespondentQuestion]:
    """Every Respondent question of the version's current Verdicts on Trials not dropped, in Trial then Criterion order
    (not deduplicated)."""
    rows = await reader.fetch(
        f"SELECT {_RQ_COLS} FROM {reader.table('respondent_question')} q "
        f"JOIN {reader.table('trial')} t ON t.nct_id = q.nct_id AND t.eligibility_hash = q.eligibility_hash "
        f"JOIN {reader.table('criterion')} c ON c.id = q.criterion_id "
        "WHERE q.profile_version_id = $1 AND NOT t.dropped ORDER BY q.nct_id, c.ordinal", (version_id,))
    return [_respondent_question(r) for r in rows]

# Verdicts are NOT written here: app.worldmodel.timeline.record_verdict (World Model relate → projector).
