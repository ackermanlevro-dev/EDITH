from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

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
    metadata: dict = field(default_factory=dict)


class KnowledgeSource(ABC):
    """Where documents come from. Ingestion only ever talks to this interface -
    adding a new source type later (web pages, a wiki export, ...) means
    writing one new class, not touching the pipeline."""

    @abstractmethod
    def discover(self) -> list[RawDocument]: ...


class FileSource(KnowledgeSource):
    """An explicit file, or every .md file under a directory - the upload path."""

    def __init__(
        self,
        paths: list[Path],
        *,
        domain: str | None = None,
        category: str | None = None,
    ):
        self._paths = paths
        self._domain = domain
        self._category = category

    def discover(self) -> list[RawDocument]:
        docs = []
        for path in self._paths:
            content = path.read_text(encoding="utf-8")
            docs.append(
                RawDocument(
                    source_type="file",
                    source_path=str(path.resolve()),
                    title=path.stem,
                    mime_type="text/markdown" if path.suffix == ".md" else "text/plain",
                    content=content,
                    content_hash=hash_content(content),
                    domain=self._domain,
                    category=self._category,
                )
            )
        return docs


class ObsidianSource(KnowledgeSource):
    """Walks a vault directory for Markdown files. Full incremental vault
    sync with backlinks/frontmatter is Phase 3 - this exercises the same
    ingestion pipeline against a real vault today, folder-as-category."""

    def __init__(self, vault_path: Path, *, ignore_patterns: set[str] | None = None):
        self._vault_path = vault_path
        self._ignore = ignore_patterns or DEFAULT_IGNORE_PATTERNS

    def discover(self) -> list[RawDocument]:
        docs = []
        for path in sorted(self._vault_path.rglob("*.md")):
            if any(part in self._ignore for part in path.parts):
                continue

            content = path.read_text(encoding="utf-8")
            rel = path.relative_to(self._vault_path)
            docs.append(
                RawDocument(
                    source_type="obsidian",
                    source_path=str(path.resolve()),
                    title=path.stem,
                    mime_type="text/markdown",
                    content=content,
                    content_hash=hash_content(content),
                    category=str(rel.parent) if rel.parent != Path(".") else None,
                )
            )
        return docs
