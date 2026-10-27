"""The same PDF bytes are parsed once. A later add reuses the saved read."""
from datetime import date

from app.extraction import ExtractedBlock, ExtractedDocument, ExtractedPage
from app.record.parse_cache import from_document, load, save
from app.record.referral import read_pdf
from app.record.types import Document, DocumentHash, Page, PatientId, Region


class _Once:
    def __init__(self, parsed: ExtractedDocument):
        self.parsed = parsed
        self.reads = 0

    def read(self, content: bytes) -> ExtractedDocument:
        self.reads += 1
        return self.parsed


def test_a_saved_parse_is_reused_and_the_parser_is_not_called_again(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr("app.record.parse_cache.CACHE", tmp_path)
    parsed = ExtractedDocument(pages=(ExtractedPage(
        number=1, text="PSA 4.2", blocks=(ExtractedBlock(0, "Text", "PSA 4.2", 0.1, 0.2, 0.4, 0.3),)),))
    parser = _Once(parsed)
    content = b"%PDF-1.4 saved"

    first, name = read_pdf(parser, "letter.pdf", content)
    second, again = read_pdf(parser, "letter.pdf", content)

    assert parser.reads == 1
    assert (second, again) == (first, name)
    assert load(content, tmp_path)[0].pages[0].blocks[0].text == "PSA 4.2"


def test_a_stored_letter_can_be_saved_as_the_parse(tmp_path):
    doc = Document(
        hash=DocumentHash("a" * 64), patient_id=PatientId("pt"), filename="referral.pdf",
        pages=(Page(number=1, text="Lu-177"),), uploaded_at=date(2026, 2, 9),
        regions=(Region("a" * 12 + ":p1:b0", 1, 0, "Text", "Lu-177", 0.1, 0.2, 0.5, 0.3),))
    parsed, name = from_document(doc)
    save(b"%PDF-stored", parsed, name, tmp_path)

    loaded, filename = load(b"%PDF-stored", tmp_path)
    block = loaded.pages[0].blocks[0]
    assert filename == "referral.pdf"
    assert (block.text, block.xmin, block.ymax) == ("Lu-177", 0.1, 0.3)
