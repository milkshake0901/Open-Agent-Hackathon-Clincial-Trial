"""app/matching/evaluator.py — Evaluator agent: the ONLY producer of ValidatedResults.

Two layers: a pure structural check (does the cited Fact exist in this Profile version, is
outcome/citation consistent) and a judge-lane semantic check (does that Fact support the claim).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.ctx import Ctx
from app.matching.types import CriterionResult, Outcome, Rejection, ValidatedResults
from app.record import ProfileVersion
from app.trials import Criterion
from app import trace


@dataclass(frozen=True)
class Review:
    results: tuple[CriterionResult, ...]
    rejections: tuple[Rejection, ...]


def validate_structure(results: tuple[CriterionResult, ...], criteria: tuple[Criterion, ...],
                       profile: ProfileVersion) -> tuple[Rejection, ...]:
    """PURE.
    # TODO
    #   every criterion appears exactly once (missing → rejection "no result for criterion")
    #   outcome in {MET, NOT_MET} requires citation with fact_id in profile.fact_ids, else reject
    #   outcome UNKNOWN requires citation is None, else reject
    #   citation.document_hash/page must equal the Fact's (Matcher may not invent provenance)
    """
    raise NotImplementedError


async def validate_support(ctx: Ctx, results: tuple[CriterionResult, ...], criteria: tuple[Criterion, ...],
                           profile: ProfileVersion, run_id: trace.RunId) -> tuple[Rejection, ...]:
    """Judge lane, one yes/no call per cited result: "Does Fact <subject value unit observed_on>
    support claim '<criterion text>' being <outcome>?" Only runs on results that passed structure."""
    raise NotImplementedError


async def review(ctx: Ctx, results: tuple[CriterionResult, ...], criteria: tuple[Criterion, ...],
                 profile: ProfileVersion, run_id: trace.RunId) -> Review:
    """Deterministic structure check first (no model call); the judge-lane support check runs only
    on results that passed it. Emits EvaluatorRejected or EvaluatorApproved to the trace."""
    raise NotImplementedError


def approve(results: tuple[CriterionResult, ...]) -> ValidatedResults:
    """Private-by-convention constructor of the newtype; called only after review() returned no rejections."""
    raise NotImplementedError


def downgrade(results: tuple[CriterionResult, ...], rejections: tuple[Rejection, ...]) -> ValidatedResults:
    """PURE. Every rejected result becomes UNKNOWN with citation None and rationale prefixed
    'unsupported after N attempts:'. The output is valid by construction, so it is ValidatedResults."""
    raise NotImplementedError
