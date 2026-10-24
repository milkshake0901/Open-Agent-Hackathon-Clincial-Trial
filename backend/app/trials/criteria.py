"""app/trials/criteria.py — eligibility text → Criteria. Deterministic first, model as fallback."""
from __future__ import annotations

import re

from app.ctx import Ctx
from app.trials import Criterion, CriterionId, CriterionKind, NctId

_HEADING = re.compile(r"^\s*(inclusion|exclusion)\s+criteria\s*:?\s*$", re.I | re.M)
_BULLET = re.compile(r"^(\s*)(?:[*\-•]|\d+\\?[.)])\s+(.*)$")
# Boilerplate that names no condition, so no Fact could ever decide it. It is skipped (its ordinal stays used,
# so the other ids match the Zetaris load); otherwise it would be unknown on every Trial and nothing could be eligible.
_BOILERPLATE = re.compile(r"^other protocol[- ]defined (inclusion|exclusion|inclusion/exclusion) criteria( may)? apply\.?$",
                          re.I)


def split_deterministic(nct_id: NctId, eligibility_hash: str, text: str) -> tuple[Criterion, ...]:
    """Find 'Inclusion Criteria:' / 'Exclusion Criteria:' headings (case-insensitive); within each section split on
    top-level bullet/numbered lines ('* ', '- ', '1.', '•'), merging continuation and sub-bullet lines; drop
    headings and empty items. The ordinal increments across the whole block so ids are stable. Text before the
    first heading, or with no heading at all, yields nothing (split() then asks the model)."""
    heads = list(_HEADING.finditer(text))
    items: list[tuple[CriterionKind, str]] = []
    for i, m in enumerate(heads):
        body = text[m.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        kind = CriterionKind(m.group(1).lower())
        current: list[str] | None = None
        for line in body.splitlines():
            if not line.strip():
                continue
            b = _BULLET.match(line)
            if b and len(b.group(1)) < 2:
                if current:
                    items.append((kind, " ".join(current)))
                current = [b.group(2).strip()]
            elif current is not None:
                current.append((b.group(2) if b else line).strip())
            else:
                current = [line.strip()]
        if current:
            items.append((kind, " ".join(current)))
    prefix = f"{nct_id}:{eligibility_hash[:8]}"
    return tuple(Criterion(id=CriterionId(f"{prefix}:{n}"), nct_id=nct_id, eligibility_hash=eligibility_hash,
                           kind=kind, ordinal=n, text=item)
                 for n, (kind, item) in enumerate(items, 1) if not _BOILERPLATE.match(item))


async def split(ctx: Ctx, nct_id: NctId, eligibility_hash: str, text: str) -> tuple[Criterion, ...]:
    """Use split_deterministic; if it yields < 2 criteria, ask the fast lane to list them (prompts/split_criteria.md)
    and re-run the kind/ordinal assignment on the model's list."""
    raise NotImplementedError
