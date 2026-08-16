from __future__ import annotations

import json
from uuid import UUID

import asyncpg

from backend.documents.models import ChunkSearchResult, DocumentRecord
from backend.ingestion.sources import RawDocument

# Reciprocal Rank Fusion, not a weighted blend of raw scores. Tried a fixed
# 0.65/0.35 blend of cosine similarity (0-1) and ts_rank (typically 0.01-0.1
# for short documents) first - it looked reasonable until live testing showed
# ts_rank's contribution was consistently ~2 orders of magnitude too small to
# move the combined score at all, silently defeating the entire point of
# hybrid search (rescuing exact technical terms a paraphrase-trained embedding
# misses). RRF sidesteps the scale mismatch by combining rank *position*
# instead of raw magnitude, so it needs no per-signal weight to guess at. 60
# is the standard constant from the original RRF paper; nothing about this
# corpus has suggested a reason to deviate from it yet.
RRF_K = 60


class DocumentRepository:
    """The only place in the app that speaks SQL. PostgreSQL/pgvector here is
    a rebuildable search index, never the source of truth - every row must
    trace back to a source_path that still exists on disk."""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def get_by_source_path(self, source_path: str) -> DocumentRecord | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM documents WHERE source_path = $1", source_path
        )
        return _row_to_document(row) if row else None

    async def list_source_paths(self, source_type: str, path_prefix: str) -> list[str]:
        """Everything currently indexed under a root, for reconciliation - e.g.
        an Obsidian sync needs this to notice a note that was deleted from the
        vault (and so never appears in a fresh discover()) but is still sitting
        in the index."""
        rows = await self._pool.fetch(
            "SELECT source_path FROM documents WHERE source_type = $1 AND starts_with(source_path, $2)",
            source_type,
            path_prefix,
        )
        return [r["source_path"] for r in rows]

    async def delete_by_source_path(self, source_path: str) -> None:
        # Cascades to document_chunks via the FK - no orphaned chunks left behind.
        await self._pool.execute("DELETE FROM documents WHERE source_path = $1", source_path)

    async def upsert_document(self, doc: RawDocument) -> UUID:
        row = await self._pool.fetchrow(
            """
            INSERT INTO documents
                (source_type, source_path, title, mime_type, content_hash, domain, category, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
            ON CONFLICT (source_path) DO UPDATE SET
                title = EXCLUDED.title,
                mime_type = EXCLUDED.mime_type,
                content_hash = EXCLUDED.content_hash,
                domain = EXCLUDED.domain,
                category = EXCLUDED.category,
                metadata = EXCLUDED.metadata,
                updated_at = now()
            RETURNING id
            """,
            doc.source_type,
            doc.source_path,
            doc.title,
            doc.mime_type,
            doc.content_hash,
            doc.domain,
            doc.category,
            json.dumps(doc.metadata or {}, default=str),
        )
        return row["id"]

    async def replace_chunks(self, document_id: UUID, chunks: list[dict]) -> None:
        """Delete + reinsert inside one transaction - the simplest way to
        guarantee a re-index never leaves duplicate or stale chunks behind."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM document_chunks WHERE document_id = $1", document_id
                )
                for c in chunks:
                    await conn.execute(
                        """
                        INSERT INTO document_chunks
                            (document_id, chunk_index, content, heading_path, embedding, metadata)
                        VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                        """,
                        document_id,
                        c["chunk_index"],
                        c["content"],
                        c["heading_path"],
                        c["embedding"],
                        json.dumps(c.get("metadata") or {}, default=str),
                    )

    async def chunk_count(self, document_id: UUID) -> int:
        return await self._pool.fetchval(
            "SELECT count(*) FROM document_chunks WHERE document_id = $1", document_id
        )

    async def set_document_tags(self, document_id: UUID, tag_names: list[str]) -> None:
        """Delete + reinsert, same pattern as replace_chunks - a re-index with
        a changed tag list must never leave the old tags attached."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM document_tags WHERE document_id = $1", document_id
                )
                for name in tag_names:
                    tag_id = await conn.fetchval(
                        """
                        INSERT INTO tags (name) VALUES ($1)
                        ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                        RETURNING id
                        """,
                        name,
                    )
                    await conn.execute(
                        """
                        INSERT INTO document_tags (document_id, tag_id)
                        VALUES ($1, $2)
                        ON CONFLICT (document_id, tag_id) DO NOTHING
                        """,
                        document_id,
                        tag_id,
                    )

    async def get_tags(self, document_id: UUID) -> list[str]:
        rows = await self._pool.fetch(
            """
            SELECT t.name FROM tags t
            JOIN document_tags dt ON dt.tag_id = t.id
            WHERE dt.document_id = $1
            ORDER BY t.name
            """,
            document_id,
        )
        return [r["name"] for r in rows]

    async def set_relationships(
        self, document_id: UUID, target_titles: list[str], relationship_type: str = "links_to"
    ) -> None:
        """target_titles are stored as plain text, not resolved to a document
        id here - see the comment on note_relationships in database/schema.sql
        for why (a link to a not-yet-created note must not go stale)."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    DELETE FROM note_relationships
                    WHERE source_document_id = $1 AND relationship_type = $2
                    """,
                    document_id,
                    relationship_type,
                )
                for title in target_titles:
                    await conn.execute(
                        """
                        INSERT INTO note_relationships (source_document_id, target_title, relationship_type)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (source_document_id, target_title, relationship_type) DO NOTHING
                        """,
                        document_id,
                        title,
                        relationship_type,
                    )

    async def get_outgoing_links(self, document_id: UUID) -> list[str]:
        rows = await self._pool.fetch(
            "SELECT target_title FROM note_relationships WHERE source_document_id = $1 ORDER BY target_title",
            document_id,
        )
        return [r["target_title"] for r in rows]

    async def get_backlinks(self, title: str) -> list[DocumentRecord]:
        """Notes that link to `title` - resolved by matching at query time
        (case-insensitively, as Obsidian itself resolves links), not by a
        stored foreign key, so a backlink appears the moment the source note
        is indexed with no separate resolution pass needed."""
        rows = await self._pool.fetch(
            """
            SELECT d.* FROM note_relationships r
            JOIN documents d ON d.id = r.source_document_id
            WHERE lower(r.target_title) = lower($1)
            ORDER BY d.title
            """,
            title,
        )
        return [_row_to_document(r) for r in rows]

    async def hybrid_search(
        self, query_embedding: list[float], query_text: str, top_k: int
    ) -> list[ChunkSearchResult]:
        rows = await self._pool.fetch(
            """
            WITH vector_ranked AS (
                SELECT id, row_number() OVER (ORDER BY embedding <=> $1) AS rank,
                       1 - (embedding <=> $1) AS vector_score
                FROM document_chunks
                ORDER BY embedding <=> $1
                LIMIT 50
            ),
            keyword_ranked AS (
                SELECT id, row_number() OVER (ORDER BY ts_rank(content_tsv, q) DESC) AS rank,
                       ts_rank(content_tsv, q) AS keyword_score
                FROM document_chunks, to_tsquery(
                    'english',
                    -- OR, not the AND that plainto_tsquery/websearch_to_tsquery default to:
                    -- a natural-language question sharing *any* content word with a chunk
                    -- is a candidate, not only a chunk containing every word in the question.
                    array_to_string(tsvector_to_array(to_tsvector('english', $2)), ' | ')
                ) AS q
                WHERE content_tsv @@ q
                ORDER BY ts_rank(content_tsv, q) DESC
                LIMIT 50
            )
            SELECT
                c.id AS chunk_id,
                c.document_id,
                c.content,
                c.heading_path,
                d.title AS document_title,
                d.source_path,
                COALESCE(v.vector_score, 0) AS vector_score,
                COALESCE(k.keyword_score, 0) AS keyword_score,
                (COALESCE(1.0 / ($4 + v.rank), 0) + COALESCE(1.0 / ($4 + k.rank), 0)) AS score
            FROM document_chunks c
            JOIN documents d ON d.id = c.document_id
            LEFT JOIN vector_ranked v ON v.id = c.id
            LEFT JOIN keyword_ranked k ON k.id = c.id
            WHERE v.id IS NOT NULL OR k.id IS NOT NULL
            ORDER BY score DESC
            LIMIT $3
            """,
            query_embedding,
            query_text,
            top_k,
            RRF_K,
        )
        return [
            ChunkSearchResult(
                chunk_id=r["chunk_id"],
                document_id=r["document_id"],
                document_title=r["document_title"],
                source_path=r["source_path"],
                heading_path=r["heading_path"],
                content=r["content"],
                score=r["score"],
                vector_score=r["vector_score"],
                keyword_score=r["keyword_score"],
            )
            for r in rows
        ]


def _row_to_document(row: asyncpg.Record) -> DocumentRecord:
    metadata = row["metadata"]
    return DocumentRecord(
        id=row["id"],
        source_type=row["source_type"],
        source_path=row["source_path"],
        title=row["title"],
        mime_type=row["mime_type"],
        content_hash=row["content_hash"],
        domain=row["domain"],
        category=row["category"],
        metadata=json.loads(metadata) if isinstance(metadata, str) else metadata,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
