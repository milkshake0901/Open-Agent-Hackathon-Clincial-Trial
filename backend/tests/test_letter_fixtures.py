"""The two recorded letters carry the cases the letter journey's tests rely on (spec #43)."""
from __future__ import annotations

import re

from tests.fixtures.letters import (NARRATIVE_LETTER, NARRATIVE_LETTER_IDENTITY, STRUCTURED_REPORT,
                                    STRUCTURED_REPORT_IDENTITY)

PARSE_KINDS = {"Text", "Title", "Section-header", "List-item", "Table", "Caption", "Page-header", "Page-footer",
               "Picture"}


def regions(document):
    return [(page.number, block) for page in document.pages for block in page.blocks]


def text_of(document, *kinds):
    return "\n".join(block.text for _, block in regions(document) if not kinds or block.kind in kinds)


def test_every_region_has_a_parse_kind_text_and_a_box_on_the_page():
    for document in (NARRATIVE_LETTER, STRUCTURED_REPORT):
        for _, block in regions(document):
            assert block.kind in PARSE_KINDS
            assert block.text.strip()
            assert 0 <= block.xmin < block.xmax <= 1 and 0 <= block.ymin < block.ymax <= 1


def test_the_narrative_letter_has_three_pages_of_day_month_dates_identity_lines_barcodes_and_footers():
    assert [page.number for page in NARRATIVE_LETTER.pages] == [1, 2, 3]
    body = text_of(NARRATIVE_LETTER, "Text", "Title", "Section-header", "List-item", "Table", "Caption")
    assert "7/2/23" in body and "23/11/23" in body
    assert "Enantone" in body and not re.search(r"testosterone\D{0,20}\d+(\.\d+)? *(nmol|ng)", body, re.I)
    assert any(block.kind == "Title" and block.text.startswith("Re: ") for _, block in regions(NARRATIVE_LETTER))
    for page in NARRATIVE_LETTER.pages:
        kinds = {block.kind for block in page.blocks}
        assert {"Caption", "Page-footer"} <= kinds
        assert any(re.fullmatch(r"OC\.\d{7}", block.text) for block in page.blocks)
    assert all(word in text_of(NARRATIVE_LETTER) for word in NARRATIVE_LETTER_IDENTITY)


def test_the_structured_report_has_written_out_dates_a_relative_date_negative_findings_and_a_header_identity():
    assert [page.number for page in STRUCTURED_REPORT.pages] == [1]
    body = text_of(STRUCTURED_REPORT)
    assert "02 October 2026" in body and "4 months ago" in body and "No meniscal tear" in body
    header = STRUCTURED_REPORT.pages[0].blocks[:2]
    assert all(word in "\n".join(block.text for block in header) for word in STRUCTURED_REPORT_IDENTITY)
