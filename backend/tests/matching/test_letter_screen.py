"""A decisive eligibility answer has to cite a region that is on the letter."""
from app.matching.letter import _Item, apply_screen
from app.record import LetterSpan
from app.trials import Criterion, CriterionId, CriterionKind, NctId


def _criterion() -> Criterion:
    return Criterion(id=CriterionId("NCT1:abcd1234:1"), nct_id=NctId("NCT1"), eligibility_hash="abcd1234abcd",
                     kind=CriterionKind.EXCLUSION, ordinal=1, text="Prior taxane chemotherapy.")


def _span() -> LetterSpan:
    return LetterSpan(id="abc:p2:b6", document_hash="abc", filename="letter.pdf", page=2, kind="Text",
                      text="Restarted taxotere from 28/11/23 to 20/3/24.", x0=0.1, y0=0.2, x1=0.9, y1=0.3)


def test_a_cited_region_keeps_its_box_and_its_words():
    judged = apply_screen((_criterion(),), (_span(),), [
        _Item(criterion_id="NCT1:abcd1234:1", outcome="met", span_id="abc:p2:b6", rationale="Taxotere is a taxane."),
    ])
    assert judged[0].outcome == "met"
    assert judged[0].quote == "Restarted taxotere from 28/11/23 to 20/3/24."
    assert (judged[0].x0, judged[0].y0) == (0.1, 0.2)


def test_an_invented_region_does_not_count():
    judged = apply_screen((_criterion(),), (_span(),), [
        _Item(criterion_id="NCT1:abcd1234:1", outcome="met", span_id="no-such-region", rationale="made up"),
    ])
    assert judged[0].outcome == "unknown"
    assert judged[0].span_id is None
    assert judged[0].quote is None
