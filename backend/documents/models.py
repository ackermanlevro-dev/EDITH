from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class DocumentRecord:
    id: UUID
    source_type: str
    source_path: str
    title: str | None
    mime_type: str | None
    content_hash: str
    domain: str | None
    category: str | None
    metadata: dict
    created_at: datetime
    updated_at: datetime


@dataclass
class ChunkSearchResult:
    chunk_id: UUID
    document_id: UUID
    document_title: str | None
    source_path: str
    heading_path: str | None
    content: str
    score: float
    vector_score: float
    keyword_score: float
