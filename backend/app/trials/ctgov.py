"""app/trials/ctgov.py — ClinicalTrials.gov access. Private to the trials module."""
from __future__ import annotations

from dataclasses import dataclass

from app.ctx import Ctx
from app.trials import Trial


@dataclass(frozen=True)
class RawStudy:
    """Parsed subset of the v2 study JSON. Transport type; never leaves this module."""
    nct_id: str
    title: str
    conditions: tuple[str, ...]
    status: str
    eligibility_text: str


async def fetch(ctx: Ctx, condition: str, location: str, max_trials: int) -> tuple[list[RawStudy], str]:
    """Returns (studies, source). Try Zetaris first: SELECT from views over a registered REST table
    (db/zetaris_register.sql). A REST table is one fixed URL, so `condition`/`location` are part of the registered
    endpoint, not pushed down from a WHERE clause. If Zetaris errors or paging stalls, fall back to httpx
    GET /api/v2/studies with pageToken, ≤50 req/min. The two paths produce RawStudy identically so the rest of the
    module cannot tell."""
    raise NotImplementedError


def eligibility_hash(text: str) -> str:
    """sha256 over whitespace-normalised text so cosmetic upstream edits do not trigger re-judging."""
    raise NotImplementedError


def to_trial(raw: RawStudy, source: str, fetched_at: str) -> Trial:
    raise NotImplementedError
