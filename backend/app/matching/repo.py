"""app/matching/repo.py — SQL for verdict, criterion_result, doctor_question."""
from __future__ import annotations

from app.matching.types import DoctorQuestion, Verdict
from app.record import ProfileVersionId
from app.sql.reader import SqlReader
from app.sql.writer import PgWriter
from app.trials import NctId, Trial


async def trials_needing_verdict(reader: SqlReader, version_id: ProfileVersionId, only: set[NctId] | None) -> tuple[list[Trial], list[NctId]]:
    """The idempotent plan, in one query (see loop.plan)."""
    raise NotImplementedError

async def verdict(reader: SqlReader, nct_id: NctId, version_id: ProfileVersionId, *, with_results: bool) -> Verdict | None:
    raise NotImplementedError

async def verdicts_for_version(reader: SqlReader, version_id: ProfileVersionId) -> list[Verdict]:
    raise NotImplementedError

async def questions_for_version(reader: SqlReader, version_id: ProfileVersionId) -> list[DoctorQuestion]:
    raise NotImplementedError

# Verdicts are NOT written here: app.worldmodel.timeline.record_verdict (World Model relate → projector).
