"""app/api/schemas.py — wire models built FROM domain types; never imported by domain modules.
The frontend generates its TypeScript types from /openapi.json, so this is the one wire definition."""
from __future__ import annotations

from pydantic import BaseModel


class UploadAccepted(BaseModel):
    document_hash: str
    run_id: str
    deduplicated: bool


class RunAccepted(BaseModel):
    run_id: str


# TODO: VersionOut, FactOut, CitationOut, VerdictSummaryOut, VerdictOut, VerdictChangeOut,
#       DoctorQuestionOut, SyncReportOut, RunLogOut, TraceTreeOut, HealthOut — see docs/api.md.
