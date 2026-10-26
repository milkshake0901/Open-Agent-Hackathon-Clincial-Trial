"""app/trace/events.py — THE single list of trace event kinds (discriminated union).

Everything else derives from this: Event.kind strings, projections, the API's trace schema
(api/schemas.py builds its union from RunEvent.__args__), and the frontend's TS type is generated
from the OpenAPI document. Adding an event kind means editing this file only.
"""
from __future__ import annotations

from typing import Annotated, ClassVar, Literal, Union

from pydantic import BaseModel, Field


class _Base(BaseModel):
    """Payload only. The envelope (event_id, actor, causation_id, correlation_id, llm_call_ids)
    is added by app.trace.append, so events stay plain data. An event with a `log_step` is also written to the
    log file (app.logfile) under that step name, with the run id and its payload."""
    log_step: ClassVar[str | None] = None
    actor: str

    def summary(self) -> str:
        """One line for the trace list. Each subclass overrides."""
        raise NotImplementedError


# ---- ingest run ------------------------------------------------------------
class IngestStarted(_Base):
    kind: Literal["ingest.started"] = "ingest.started"
    document_hash: str
    pages: int

class IntakeDrafted(_Base):
    kind: Literal["intake.drafted"] = "intake.drafted"
    attempt: int
    drafts: list[dict]           # DraftFact as dict; kept in the run so AwaitingPatient survives restart
    model_answered: str

class CriticReviewed(_Base):
    kind: Literal["critic.reviewed"] = "critic.reviewed"
    attempt: int
    findings: list[dict]         # Finding as dict

class IngestRetried(_Base):
    kind: Literal["intake.retried"] = "intake.retried"
    attempt: int
    feedback: list[str]

class RunAwaitingPatient(_Base):
    kind: Literal["run.awaiting_patient"] = "run.awaiting_patient"
    conflicts: list[dict]
    accepted_drafts: list[dict]

class PatientResolved(_Base):
    kind: Literal["patient.resolved"] = "patient.resolved"
    resolutions: list[dict]

class RunAwaitingReview(_Base):
    """A letter's drafted Facts park here, uncommitted, for Letter review. `withdrawn`: accepted Fact ids a resolved
    Conflict left out of the next version, applied when the review commits."""
    kind: Literal["run.awaiting_review"] = "run.awaiting_review"
    drafts: list[dict]
    withdrawn: list[str] = []

class ReviewAnswered(_Base):
    """The Respondent's word on one parked draft (its index in RunAwaitingReview.drafts): keep ("Looks right") or
    drop ("Not right", with what it should be, if they said)."""
    kind: Literal["review.answered"] = "review.answered"
    index: int
    decision: Literal["keep", "drop"]
    correction: str | None = None

class ProfileCommitted(_Base):
    kind: Literal["profile.committed"] = "profile.committed"
    profile_version_id: str
    version_number: int
    facts_added: int

class RunRejected(_Base):
    kind: Literal["run.rejected"] = "run.rejected"
    reason: str

# ---- rescan run ------------------------------------------------------------
class RescanPlanned(_Base):
    log_step: ClassVar[str | None] = "matching.rescan.started"
    kind: Literal["rescan.planned"] = "rescan.planned"
    profile_version_id: str
    to_judge: list[str]
    skipped_existing: list[str]

class MatcherProposed(_Base):
    kind: Literal["matcher.proposed"] = "matcher.proposed"
    nct_id: str
    attempt: int
    results: list[dict]
    model_answered: str

class EvaluatorRejected(_Base):
    kind: Literal["evaluator.rejected"] = "evaluator.rejected"
    nct_id: str
    attempt: int
    rejections: list[dict]
    model_answered: str | None   # None when only structural checks fired

class EvaluatorApproved(_Base):
    kind: Literal["evaluator.approved"] = "evaluator.approved"
    nct_id: str
    attempt: int
    model_answered: str | None

class MatcherRetried(_Base):
    kind: Literal["matcher.retried"] = "matcher.retried"
    nct_id: str
    attempt: int

class TrialJudged(_Base):
    log_step: ClassVar[str | None] = "matching.trial_judged"
    kind: Literal["trial.judged"] = "trial.judged"
    nct_id: str
    outcome: str
    attempts: int
    unsupported_downgraded: int
    degraded: bool               # True when the loop hit its bound and claims were downgraded to unknown
    questions: int               # Doctor questions
    respondent_questions: int = 0

class RescanFinished(_Base):
    log_step: ClassVar[str | None] = "matching.rescan.finished"
    kind: Literal["rescan.finished"] = "rescan.finished"
    judged: list[str]
    failed: list[list[str]]

# ---- cross-cutting -----------------------------------------------------------
class LlmCalled(_Base):
    """Emitted by app.llm for every completion. Details live in the llm_call table (app.trace.LlmCall);
    the event carries only the id so the trace can show which model answered each step."""
    kind: Literal["llm.called"] = "llm.called"
    llm_call_id: str
    lane: str
    model_answered: str


RunEvent = Annotated[
    Union[
        IngestStarted, IntakeDrafted, CriticReviewed, IngestRetried, RunAwaitingPatient, PatientResolved,
        RunAwaitingReview, ReviewAnswered, ProfileCommitted, RunRejected, RescanPlanned, MatcherProposed, EvaluatorRejected, EvaluatorApproved,
        MatcherRetried, TrialJudged, RescanFinished, LlmCalled,
    ],
    Field(discriminator="kind"),
]
