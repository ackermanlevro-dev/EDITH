from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from backend.ai.embeddings import EmbeddingProvider
from backend.documents.repository import DocumentRepository
from backend.ingestion.chunker import chunk_markdown
from backend.ingestion.sources import KnowledgeSource, ObsidianSource, RawDocument


@dataclass
class IndexResult:
    source_path: str
    status: str  # "created" | "updated" | "unchanged"
    chunk_count: int


@dataclass
class SyncResult:
    """Unlike a plain index_source() run, a vault sync knows the full set of
    files that currently exist - so, unlike an ad-hoc file upload, it can also
    tell what's been deleted and needs to be dropped from the index."""

    indexed: list[IndexResult] = field(default_factory=list)  # created/updated/unchanged
    deleted: list[str] = field(default_factory=list)


class IngestionPipeline:
    """Source file -> hash check -> chunk -> embed -> store. The one path
    every document takes regardless of where it came from."""

    def __init__(
        self,
        repository: DocumentRepository,
        embeddings: EmbeddingProvider,
        chunk_size: int,
        chunk_overlap: int,
    ):
        self._repository = repository
        self._embeddings = embeddings
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    async def index_source(self, source: KnowledgeSource) -> list[IndexResult]:
        return [await self._index_document(doc) for doc in source.discover()]

    async def sync_vault(self, source: ObsidianSource, vault_path: Path) -> SyncResult:
        """Reconciling sync: index every current file, then remove any
        previously-indexed document under this vault that no longer exists on
        disk (deleted or renamed). Scoped by path prefix so this never touches
        documents indexed from anywhere else (e.g. one-off file uploads)."""
        discovered = source.discover()
        discovered_paths = {doc.source_path for doc in discovered}

        result = SyncResult(indexed=[await self._index_document(doc) for doc in discovered])

        vault_root = str(vault_path.resolve())
        existing_paths = await self._repository.list_source_paths("obsidian", vault_root)
        for stale_path in existing_paths:
            if stale_path not in discovered_paths:
                await self._repository.delete_by_source_path(stale_path)
                result.deleted.append(stale_path)

        return result

    async def _index_document(self, doc: RawDocument) -> IndexResult:
        existing = await self._repository.get_by_source_path(doc.source_path)

        if existing and existing.content_hash == doc.content_hash:
            return IndexResult(source_path=doc.source_path, status="unchanged", chunk_count=0)

        document_id = await self._repository.upsert_document(doc)

        chunks = chunk_markdown(
            doc.content,
            title=doc.title,
            chunk_size=self._chunk_size,
            chunk_overlap=self._chunk_overlap,
        )

        rows = []
        for chunk in chunks:
            vector = await self._embeddings.embed(chunk.content)
            rows.append(
                {
                    "chunk_index": chunk.chunk_index,
                    "content": chunk.content,
                    "heading_path": chunk.heading_path,
                    "embedding": vector,
                    "metadata": chunk.metadata,
                }
            )

        # Full delete+reinsert per document keeps this correct with no extra
        # bookkeeping; fine at personal-knowledge-base scale. Revisit only if
        # per-document chunk counts grow large enough to make that wasteful.
        await self._repository.replace_chunks(document_id, rows)
        await self._repository.set_document_tags(document_id, doc.tags)
        await self._repository.set_relationships(document_id, doc.links)

        status = "updated" if existing else "created"
        return IndexResult(source_path=doc.source_path, status=status, chunk_count=len(rows))
