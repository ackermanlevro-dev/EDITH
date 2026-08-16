from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from backend.ai.embeddings import EmbeddingProvider
from backend.documents.repository import DocumentRepository
from backend.ingestion.pipeline import IngestionPipeline
from backend.ingestion.sources import FileSource
from backend.rag.generation import RETRIEVAL_SCORE_THRESHOLD

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
MAX_RELATED = 5


@dataclass
class RelatedNote:
    title: str
    source_path: str
    score: float


@dataclass
class CreatedNote:
    path: Path
    related: list[RelatedNote]


def sanitize_filename(title: str) -> str:
    cleaned = _INVALID_FILENAME_CHARS.sub("", title).strip().strip(".")
    return cleaned or "Untitled"


class NoteWriter:
    """Writes real .md files into the Obsidian vault - the vault stays the
    source of truth (see database/schema.sql), this only ever adds new files,
    never touches an existing one, matching 'don't modify my notes unless
    explicitly instructed' - here, asking to save something *is* that
    instruction. Every new note is auto-linked to related existing notes via
    [[wikilinks]] using the same retrieval the chat/search use, so Obsidian's
    graph view gets real edges instead of an isolated new node - and because
    the link is one-directional (new note -> existing notes), it never has to
    edit an existing note to do it; Obsidian computes backlinks on its own."""

    def __init__(
        self,
        vault_path: Path,
        repository: DocumentRepository,
        embeddings: EmbeddingProvider,
        pipeline: IngestionPipeline,
    ):
        self._vault_path = vault_path
        self._repository = repository
        self._embeddings = embeddings
        self._pipeline = pipeline

    async def create_note(
        self,
        title: str,
        content: str,
        *,
        folder: str | None = None,
        tags: list[str] | None = None,
    ) -> CreatedNote:
        related = await self._find_related(content)

        dest_dir = (self._vault_path / folder) if folder else self._vault_path
        dest_dir.mkdir(parents=True, exist_ok=True)

        filename = sanitize_filename(title)
        dest = dest_dir / f"{filename}.md"
        n = 2
        while dest.exists():  # never overwrite an existing note, including one we just made
            dest = dest_dir / f"{filename} ({n}).md"
            n += 1

        dest.write_text(self._render(title, content, tags, related), encoding="utf-8")

        # Index right away - "saved" should mean searchable now, not after the
        # user remembers to run a vault sync. source_type="obsidian" (not the
        # FileSource default of "file") so this note is later covered by
        # vault sync's deletion reconciliation, like every other vault note.
        await self._pipeline.index_source(FileSource([dest], source_type="obsidian"))

        return CreatedNote(path=dest, related=related)

    async def _find_related(self, content: str) -> list[RelatedNote]:
        embedding = await self._embeddings.embed(content)
        # Search the whole index (not just this vault) - it may include
        # documents uploaded from outside the vault. A [[wikilink]] only
        # means something in Obsidian's graph if the target file physically
        # exists inside the vault tree; linking to something Obsidian can't
        # see would render as a broken reference, not a real connection.
        results = await self._repository.hybrid_search(embedding, content, MAX_RELATED * 4)
        vault_root = str(self._vault_path.resolve())

        seen_documents: set = set()
        related: list[RelatedNote] = []
        for r in results:
            if r.score < RETRIEVAL_SCORE_THRESHOLD or r.document_id in seen_documents:
                continue
            if not r.source_path.startswith(vault_root):
                continue
            seen_documents.add(r.document_id)
            related.append(
                RelatedNote(
                    title=r.document_title or Path(r.source_path).stem,
                    source_path=r.source_path,
                    score=r.score,
                )
            )
            if len(related) >= MAX_RELATED:
                break
        return related

    @staticmethod
    def _render(title: str, content: str, tags: list[str] | None, related: list[RelatedNote]) -> str:
        created = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        frontmatter = ["---", f"created: {created}", "source: second-brain"]
        if tags:
            frontmatter.append(f"tags: [{', '.join(tags)}]")
        frontmatter.append("---")

        body = f"{chr(10).join(frontmatter)}\n\n# {title}\n\n{content.strip()}\n"

        if related:
            links = "\n".join(f"- [[{r.title}]]" for r in related)
            body += f"\n## Related\n\n{links}\n"

        return body
