"""app/trials/criteria.py — eligibility text → Criteria. Deterministic first, model as fallback."""
from __future__ import annotations

from app.ctx import Ctx
from app.trials import Criterion, CriterionKind, NctId


def split_deterministic(nct_id: NctId, eligibility_hash: str, text: str) -> tuple[Criterion, ...]:
    """# TODO: find 'Inclusion Criteria:' / 'Exclusion Criteria:' headings (case-insensitive); within each section split on
    bullet/numbered lines ('* ', '- ', '1.', '•'); merge continuation lines; drop headings and empty items;
    ordinal increments across the whole block so ids are stable."""
    raise NotImplementedError


async def split(ctx: Ctx, nct_id: NctId, eligibility_hash: str, text: str) -> tuple[Criterion, ...]:
    """Use split_deterministic; if it yields < 2 criteria, ask the fast lane to list them (prompts/split_criteria.md)
    and re-run the kind/ordinal assignment on the model's list."""
    raise NotImplementedError
