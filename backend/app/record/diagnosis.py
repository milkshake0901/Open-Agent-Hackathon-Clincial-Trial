"""app/record/diagnosis.py — a shortlist of Condition labels for the free-text diagnosis (#33, ADR 0005). Fast lane:
the model turns the words into search phrases, code finds the stored labels containing them, the model picks the
ones that fit. The model sees only the diagnosis words and the candidate labels."""
from __future__ import annotations

from pydantic import BaseModel

from app import trials
from app.ctx import Ctx
from app.llm import Lane, complete

MAX_PHRASES = 8       # search phrases asked of the model
MAX_CANDIDATES = 40   # candidate labels shown to the model, most used first
SHORTLIST_SIZE = 6    # labels offered to the Respondent


# Required, no defaults: a reply in another shape (seen live: Nightshift answering from a cached reply to an older
# prompt) must fail validation and be retried, not read as "no phrases" and give an empty shortlist.
class _PhrasesOut(BaseModel):
    phrases: list[str]


class _PickOut(BaseModel):
    labels: list[str]


PHRASES_SYSTEM = f"""You turn a patient's or carer's own description of a diagnosis into search phrases for finding the
condition in ClinicalTrials.gov condition lists. Answer with JSON only: {{"phrases": ["...", "..."]}}
- At most {MAX_PHRASES} search phrases, most likely first: the condition's names, synonyms, abbreviations spelled out
  in full ("ACL" -> "anterior cruciate ligament"), and broader and narrower names ("lung cancer",
  "non-small cell lung cancer").
- Each phrase is a few plain words that a condition name would contain; no punctuation, no explanation.
- If the description is not a diagnosis, answer {{"phrases": []}}."""

PICK_SYSTEM = f"""You choose a shortlist of condition labels, exactly as clinical trials list them, that fit a patient's
or carer's own description of a diagnosis. Answer with JSON only: {{"labels": ["...", "..."]}}
- Pick at most {SHORTLIST_SIZE} labels from the candidates, copied exactly, best fit first.
- Pick only labels that name what the description means, or a more specific or broader name of it; never a
  different condition.
- If no candidate fits, answer {{"labels": []}}."""


async def shortlist(ctx: Ctx, text: str) -> tuple[trials.ConditionLabel, ...]:
    """Up to SHORTLIST_SIZE stored Condition labels that fit the diagnosis words, best fit first; empty when none
    does. At most two fast-lane calls, none for judging. Raises llm.LlmUnavailable."""
    # Each user message names its task: the runtime can answer a repeated user message from its cache whatever the
    # system prompt says, so neither call sends only the diagnosis words.
    words = f"Diagnosis, in the Respondent's words:\n{text}"
    phrases = (await complete(ctx, Lane.FAST, system=PHRASES_SYSTEM, user=f"Search phrases for this diagnosis.\n{words}",
                              out=_PhrasesOut,
                              run_id=None)).value.phrases
    phrases = [p for p in (" ".join(p.split()) for p in phrases[:MAX_PHRASES]) if p]
    candidates = await trials.search_condition_labels(ctx, phrases, limit=MAX_CANDIDATES) if phrases else []
    if not candidates:
        return ()
    listed = "\n".join(f"- {one.label}" for one in candidates)
    picked = (await complete(ctx, Lane.FAST, system=PICK_SYSTEM, user=f"Shortlist of condition labels for this diagnosis.\n{words}\n\nCandidate labels:\n{listed}",
                             out=_PickOut, run_id=None)).value.labels
    by_key = {trials.label_key(one.label): one for one in candidates}
    chosen: dict[str, trials.ConditionLabel] = {}
    for label in picked:
        if (one := by_key.get(trials.label_key(label))) is not None:
            chosen.setdefault(trials.label_key(label), one)
    return tuple(chosen.values())[:SHORTLIST_SIZE]
