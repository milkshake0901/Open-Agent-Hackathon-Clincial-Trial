"""app/matching/evaluator.py — Evaluator agent: the ONLY producer of ValidatedResults.

Two layers: a pure structural check (does the cited Fact exist in this Profile version, is
outcome/citation consistent) and a judge-lane semantic check (does that Fact support the claim).
"""
from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from app.ctx import Ctx
from app.llm import Lane, complete
from app.matching.types import CriterionResult, Outcome, Rejection, ValidatedResults
from app.record import ProfileVersion
from app.trials import Criterion
from app import trace


@dataclass(frozen=True)
class Review:
    results: tuple[CriterionResult, ...]
    rejections: tuple[Rejection, ...]
    model_answered: str | None = None   # None when no support check ran (nothing cited, or structure failed)


class _CheckOut(BaseModel):
    criterion_id: str
    supported: bool
    reason: str = ""


class _JudgeOut(BaseModel):
    checks: list[_CheckOut]


JUDGE_SYSTEM = """You are the Evaluator of a clinical-trial matching service. Each CLAIM line says a patient Fact shows
an eligibility Criterion is met or not met. For an exclusion Criterion, "met" means the patient has what it
excludes. Decide for each claim whether the Fact, read literally (value, date and quote), supports it. Vague words
do not support a precise claim. Answer with JSON only:
{"checks": [{"criterion_id": "...", "supported": true | false, "reason": "one short sentence"}]}"""


def validate_structure(results: tuple[CriterionResult, ...], criteria: tuple[Criterion, ...],
                       profile: ProfileVersion) -> tuple[Rejection, ...]:
    """PURE. Every Criterion has exactly one result; met / not met cites a Fact of this Profile version with that
    Fact's own provenance; unknown cites nothing. An uncited claim is rejected here, never stored."""
    facts = {f.id: f for f in profile.facts}
    out: list[Rejection] = []
    seen: dict[str, int] = {}
    for r in results:
        seen[r.criterion_id] = seen.get(r.criterion_id, 0) + 1
    for c in criteria:
        if c.id not in seen:
            out.append(Rejection(c.id, "no result for criterion"))
        elif seen[c.id] > 1:
            out.append(Rejection(c.id, "more than one result for criterion"))
    for r in results:
        if seen[r.criterion_id] > 1:
            continue
        if r.outcome == Outcome.UNKNOWN:
            if r.citation is not None:
                out.append(Rejection(r.criterion_id, "an unknown result must not cite a Fact"))
            continue
        if r.citation is None:
            out.append(Rejection(r.criterion_id, f"a {r.outcome} result must cite a Fact (uncited claim)"))
            continue
        f = facts.get(r.citation.fact_id)
        if f is None or r.citation.fact_id not in profile.fact_ids:
            out.append(Rejection(r.criterion_id, f"fact_id {r.citation.fact_id} not in profile version"))
        elif (r.citation.document_hash, r.citation.page, r.citation.quote) != (f.document_hash, f.page, f.quote):
            out.append(Rejection(r.criterion_id, "citation provenance does not match the Fact"))
    return tuple(out)


def _claim(r: CriterionResult, c: Criterion, profile: ProfileVersion) -> str:
    f = next(f for f in profile.facts if f.id == r.citation.fact_id)
    unit = f" {f.unit}" if f.unit else ""
    return (f'CLAIM {c.id} | criterion ({c.kind}): {c.text} | claimed: {r.outcome} | fact: {f.subject} = '
            f'{f.value}{unit}, observed {f.observed_on.isoformat()}, quote "{f.quote}"')


async def validate_support(ctx: Ctx, results: tuple[CriterionResult, ...], criteria: tuple[Criterion, ...],
                           profile: ProfileVersion, run_id: trace.RunId) -> tuple[tuple[Rejection, ...], str | None]:
    """Judge lane, ONE call per attempt listing every cited claim (one yes/no each): does Fact <subject value unit
    observed_on quote> support '<criterion text>' being <outcome>? A claim the judge does not confirm is rejected.
    Only runs on results that passed structure; no call when nothing is cited."""
    by_id = {c.id: c for c in criteria}
    cited = [r for r in results if r.citation is not None]
    if not cited:
        return (), None
    completion = await complete(ctx, Lane.JUDGE, system=JUDGE_SYSTEM,
                                user="\n".join(_claim(r, by_id[r.criterion_id], profile) for r in cited),
                                out=_JudgeOut, run_id=run_id)
    checks = {c.criterion_id: c for c in completion.value.checks}
    out = []
    for r in cited:
        check = checks.get(r.criterion_id)
        if check is None:
            out.append(Rejection(r.criterion_id, "the Evaluator could not confirm the cited Fact supports this"))
        elif not check.supported:
            out.append(Rejection(r.criterion_id, check.reason or "the cited Fact does not support this outcome"))
    return tuple(out), completion.model_answered


async def review(ctx: Ctx, results: tuple[CriterionResult, ...], criteria: tuple[Criterion, ...],
                 profile: ProfileVersion, run_id: trace.RunId) -> Review:
    """Deterministic structure check first; the judge-lane support check runs only on results that passed it
    (and only when every Criterion has exactly one result). The loop traces the outcome."""
    structural = validate_structure(results, criteria, profile)
    rejected = {r.criterion_id for r in structural}
    if any(r.reason.startswith(("no result", "more than one")) for r in structural):
        return Review(results, structural)
    support, model = await validate_support(ctx, tuple(r for r in results if r.criterion_id not in rejected),
                                            criteria, profile, run_id)
    return Review(results, structural + support, model)


def approve(results: tuple[CriterionResult, ...]) -> ValidatedResults:
    """Private-by-convention constructor of the newtype; called only after review() returned no rejections."""
    return ValidatedResults(results)


def downgrade(results: tuple[CriterionResult, ...], rejections: tuple[Rejection, ...],
              criteria: tuple[Criterion, ...], attempts: int) -> ValidatedResults:
    """PURE. Every rejected result becomes UNKNOWN with citation None and rationale prefixed
    'unsupported after N attempts:'; a Criterion with no usable result becomes UNKNOWN too. The output has exactly
    one result per Criterion, in Criterion order, so it is valid by construction: ValidatedResults."""
    reasons: dict[str, str] = {}
    for r in rejections:
        reasons.setdefault(r.criterion_id, r.reason)
    firsts: dict[str, CriterionResult] = {}
    for r in results:
        firsts.setdefault(r.criterion_id, r)
    out = []
    for c in criteria:
        r = firsts.get(c.id)
        if r is None or c.id in reasons:
            reason = reasons.get(c.id, "no result for criterion")
            out.append(CriterionResult(criterion_id=c.id, outcome=Outcome.UNKNOWN, citation=None,
                                       rationale=f"unsupported after {attempts} attempts: {reason}"))
        else:
            out.append(r)
    return ValidatedResults(out)

