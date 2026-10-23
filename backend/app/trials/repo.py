"""app/trials/repo.py"""
from __future__ import annotations

from app.sql.reader import SqlReader
from app.sql.writer import PgWriter
from app.trials import Criterion, NctId, Trial


async def trial(reader: SqlReader, nct_id: NctId) -> Trial | None: raise NotImplementedError
async def active_trials(reader: SqlReader) -> list[Trial]: raise NotImplementedError
async def criteria(reader: SqlReader, nct_id: NctId, eligibility_hash: str) -> tuple[Criterion, ...]: raise NotImplementedError
# Trials and Criteria are NOT written here: app.worldmodel.timeline.record_trials (World Model ingest → projector).
