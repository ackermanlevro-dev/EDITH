from pathlib import Path

from backend.ingestion.loaders import PDFLoader, TextLoader, get_loader, supported_extensions
from tests.pdf_fixtures import make_test_pdf as _make_test_pdf


def test_text_loader_reads_md_and_txt(tmp_path):
    loader = TextLoader()
    md = tmp_path / "note.md"
    md.write_text("# Title\n\nBody.\n")
    assert loader.can_load(md)
    assert loader.load(md) == "# Title\n\nBody.\n"

    txt = tmp_path / "note.txt"
    txt.write_text("plain text")
    assert loader.can_load(txt)


def test_text_loader_rejects_pdf():
    assert not TextLoader().can_load(Path("x.pdf"))


def test_pdf_loader_extracts_text_with_page_marker(tmp_path):
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(_make_test_pdf("Hello PDF world"))

    loader = PDFLoader()
    assert loader.can_load(pdf_path)
    text = loader.load(pdf_path)

    assert "Hello PDF world" in text
    assert "<!-- page:1 -->" in text


def test_get_loader_dispatches_by_extension(tmp_path):
    md = tmp_path / "a.md"
    md.write_text("x")
    assert isinstance(get_loader(md), TextLoader)

    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(_make_test_pdf("x"))
    assert isinstance(get_loader(pdf), PDFLoader)


def test_get_loader_raises_for_unsupported_extension(tmp_path):
    docx = tmp_path / "a.docx"
    docx.write_bytes(b"not really a docx")
    try:
        get_loader(docx)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_supported_extensions_includes_pdf():
    assert ".pdf" in supported_extensions()
    assert ".md" in supported_extensions()
