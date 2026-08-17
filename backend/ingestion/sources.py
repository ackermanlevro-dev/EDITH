from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from backend.ingestion.frontmatter import extract_wikilinks, normalize_tags, parse_frontmatter
from backend.ingestion.loaders import get_loader, supported_extensions

_MIME_TYPES = {
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
}

# Never index these, regardless of source - secrets, VCS internals, and
# dependency trees have no business in a personal knowledge index.
DEFAULT_IGNORE_PATTERNS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".obsidian", ".env", "dist", ".vite",
}


def hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def parse_ignore_patterns(raw: str) -> set[str]:
    """Comma-separated OBSIDIAN_IGNORE_PATTERNS -> a set, merged with the
    non-negotiable defaults (never index .git, secrets, dependency trees)
    rather than letting config accidentally replace them."""
    extra = {p.strip() for p in raw.split(",") if p.strip()}
    return DEFAULT_IGNORE_PATTERNS | extra


@dataclass
class RawDocument:
    """What a KnowledgeSource hands to the ingestion pipeline - source-agnostic,
    so the pipeline never needs to know whether this came from a vault, an
    upload, or (later) a web page."""

    source_type: str
    source_path: str
    title: str
    mime_type: str
    content: str
    content_hash: str
    domain: str | None = None
    category: str | None = None
    tags: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


def _load_document(
    path: Path,
    *,
    source_type: str,
    default_domain: str | None,
    default_category: str | None,
) -> RawDocument:
    """Shared by FileSource and ObsidianSource so a document behaves
    identically regardless of where it came from. The loader (see
    ingestion/loaders.py) handles the format-specific part - turning PDF
    bytes or Markdown text into plain text - everything after that is the
    same regardless of source format.

    Frontmatter/wikilinks are a Markdown convention, so they're only parsed
    for .md files; a PDF's extracted text just becomes the content as-is.
    content_hash is computed on the loader's raw output (frontmatter
    included, for Markdown), so editing just a tag or a link still triggers
    re-indexing - but the frontmatter block itself is stripped from
    `content` before it ever reaches the chunker, so raw YAML never
    pollutes an embedding. Frontmatter domain/category override the
    caller's default rather than the other way around - a note that says
    what it is should win over a folder-path guess. Nothing from
    frontmatter is discarded even when not promoted to its own column: the
    full dict rides along in metadata.frontmatter.
    """
    loader = get_loader(path)
    raw_text = loader.load(path)

    if path.suffix.lower() == ".md":
        frontmatter, body = parse_frontmatter(raw_text)
    else:
        frontmatter, body = {}, raw_text

    return RawDocument(
        source_type=source_type,
        source_path=str(path.resolve()),
        title=path.stem,
        mime_type=_MIME_TYPES.get(path.suffix.lower(), "application/octet-stream"),
        content=body,
        content_hash=hash_content(raw_text),
        domain=frontmatter.get("domain") or default_domain,
        category=frontmatter.get("category") or default_category,
        tags=normalize_tags(frontmatter.get("tags")),
        links=extract_wikilinks(body),
        metadata={"frontmatter": frontmatter} if frontmatter else {},
    )


class KnowledgeSource(ABC):
    """Where documents come from. Ingestion only ever talks to this interface -
    adding a new source type later (web pages, a wiki export, ...) means
    writing one new class, not touching the pipeline."""

    @abstractmethod
    def discover(self) -> list[RawDocument]: ...


class FileSource(KnowledgeSource):
    """An explicit file, or every .md file under a directory - the upload
    path. source_type defaults to "file" but NoteWriter overrides it to
    "obsidian" when the file it just wrote lives inside the vault - without
    that, a note created through chat would be invisible to vault sync's
    deletion reconciliation (which only scopes to source_type='obsidian'),
    leaving an orphaned row behind the moment the user deletes it in Obsidian."""

    def __init__(
        self,
        paths: list[Path],
        *,
        domain: str | None = None,
        category: str | None = None,
        source_type: str = "file",
    ):
        self._paths = paths
        self._domain = domain
        self._category = category
        self._source_type = source_type

    def discover(self) -> list[RawDocument]:
        return [
            _load_document(
                path,
                source_type=self._source_type,
                default_domain=self._domain,
                default_category=self._category,
            )
            for path in self._paths
        ]


class ObsidianSource(KnowledgeSource):
    """Walks a vault directory for Markdown files and PDFs attached to it
    (Obsidian supports embedding PDFs directly in a vault), folder-as-category
    by default (overridable by frontmatter for Markdown). Full incremental
    sync with deletion detection lives in IngestionPipeline.sync_vault."""

    def __init__(self, vault_path: Path, *, ignore_patterns: set[str] | None = None):
        self._vault_path = vault_path
        self._ignore = ignore_patterns or DEFAULT_IGNORE_PATTERNS

    def discover(self) -> list[RawDocument]:
        paths = [
            p
            for ext in supported_extensions()
            for p in self._vault_path.rglob(f"*{ext}")
        ]

        docs = []
        for path in sorted(paths):
            if any(part in self._ignore for part in path.parts):
                continue

            rel = path.relative_to(self._vault_path)
            folder_category = str(rel.parent) if rel.parent != Path(".") else None
            docs.append(
                _load_document(
                    path,
                    source_type="obsidian",
                    default_domain=None,
                    default_category=folder_category,
                )
            )
        return docs
