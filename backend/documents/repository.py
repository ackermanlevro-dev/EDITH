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
            json.dumps(doc.metadata or {}),
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
                        json.dumps(c.get("metadata") or {}),
                    )

    async def chunk_count(self, document_id: UUID) -> int:
        return await self._pool.fetchval(
            "SELECT count(*) FROM document_chunks WHERE document_id = $1", document_id
        )

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
