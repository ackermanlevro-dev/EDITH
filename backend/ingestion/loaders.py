from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class DocumentLoader(ABC):
    """Turns bytes on disk into plain text EDITH can chunk. Nothing
    downstream (frontmatter, wikilinks, hashing, chunking) needs to know
    which loader produced the text - adding DOCX/HTML/CSV/JSON later means
    writing one new class and registering it below, not touching sources.py
    or the RAG pipeline."""

    EXTENSIONS: tuple[str, ...] = ()

    def can_load(self, path: Path) -> bool:
        return path.suffix.lower() in self.EXTENSIONS

    @abstractmethod
    def load(self, path: Path) -> str: ...


class TextLoader(DocumentLoader):
    """.md and .txt - frontmatter/wikilinks are parsed from this output
    upstream in sources.py, not this loader's concern."""

    EXTENSIONS = (".md", ".txt")

    def load(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")


class PDFLoader(DocumentLoader):
    """Extracts text per page, marking each page boundary so a chunk can
    still be attributed to a page number (spec: 'for PDFs, preserve page
    numbers'). A scanned/image-only PDF has no text layer to extract - that
    yields an empty document rather than a fabricated one; OCR is a later
    phase, not something to fake here."""

    EXTENSIONS = (".pdf",)

    def load(self, path: Path) -> str:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        parts = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                parts.append(f"<!-- page:{page_number} -->\n{text}")
        return "\n\n".join(parts)


_LOADERS: list[DocumentLoader] = [TextLoader(), PDFLoader()]


def get_loader(path: Path) -> DocumentLoader:
    for loader in _LOADERS:
        if loader.can_load(path):
            return loader
    raise ValueError(f"No loader registered for '{path.suffix}' files ({path.name})")


def supported_extensions() -> list[str]:
    return [ext for loader in _LOADERS for ext in loader.EXTENSIONS]
