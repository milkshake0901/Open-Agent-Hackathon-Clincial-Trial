"""A cited region has to be one the letter actually contains. The quote is that region's text."""
from datetime import date

from app.record.ground import citations_for, question_prompt, regions_text

SPANS = [
    {"id": "abc:p2:b6", "document_hash": "abc", "filename": "letter.pdf", "page": 2, "kind": "Text",
     "text": "Restarted taxotere from 28/11/23 to 20/3/24.", "x0": 0.1, "y0": 0.2, "x1": 0.9, "y1": 0.3,
     "page_count": 3, "patient_label": "Letter uploaded 2026-10-24"},
    {"id": "abc:p1:b2", "document_hash": "abc", "filename": "letter.pdf", "page": 1, "kind": "Caption",
     "text": "OC.9000417", "x0": 0.1, "y0": 0.05, "x1": 0.4, "y1": 0.07,
     "page_count": 3, "patient_label": "Letter uploaded 2026-10-24"},
    {"id": "abc:p3:b1", "document_hash": "abc", "filename": "letter.pdf", "page": 3, "kind": "Page-footer",
     "text": "PAGE 3/3", "x0": 0.4, "y0": 0.95, "x1": 0.6, "y1": 0.98,
     "page_count": 3, "patient_label": "Letter uploaded 2026-10-24"},
]


def test_the_model_is_shown_region_ids_and_the_as_of_date():
    prompt = question_prompt("Has this patient had chemotherapy in the last ten days?", date(2026, 10, 25), SPANS)
    assert "As of 2026-10-25." in prompt
    assert "[abc:p2:b6] Restarted taxotere from 28/11/23 to 20/3/24." in prompt
    assert "PAGE 3/3" not in regions_text(SPANS)


def test_a_citation_must_be_a_real_region_and_quotes_its_text():
    cited = citations_for(["missing", "abc:p2:b6", "abc:p2:b6"], SPANS)
    assert len(cited) == 1
    assert cited[0].span_id == "abc:p2:b6"
    assert cited[0].quote == "Restarted taxotere from 28/11/23 to 20/3/24."
    assert cited[0].page == 2
    assert (cited[0].x0, cited[0].y0, cited[0].x1, cited[0].y1) == (0.1, 0.2, 0.9, 0.3)
