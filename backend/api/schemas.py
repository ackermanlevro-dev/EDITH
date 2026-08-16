from __future__ import annotations

from pydantic import BaseModel


class IndexRequest(BaseModel):
    path: str
    source_type: str = "file"  # "file" | "obsidian"
    domain: str | None = None
    category: str | None = None


class IndexResultItem(BaseModel):
    source_path: str
    status: str
    chunk_count: int


class IndexResponse(BaseModel):
    results: list[IndexResultItem]
    # Only non-empty for source_type="obsidian" - a vault sync knows the full
    # current file set, so it can also report what's been removed. A plain
    # file/directory index doesn't reconcile deletions.
    deleted: list[str] = []


class SearchRequest(BaseModel):
    query: str
    top_k: int | None = None


class SearchResultItem(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str | None
    source_path: str
    heading_path: str | None
    content: str
    score: float
    vector_score: float
    keyword_score: float


class SearchResponse(BaseModel):
    results: list[SearchResultItem]


class ChatRequest(BaseModel):
    question: str


class SourceItem(BaseModel):
    document_id: str
    title: str | None
    source_path: str
    heading_path: str | None
    chunk_id: str
    score: float


class ChatResponse(BaseModel):
    answer: str
    intent: str
    used_personal_knowledge: bool
    sources: list[SourceItem]


class ConfigResponse(BaseModel):
    llm_model: str
    embedding_model: str
    obsidian_vault_path: str | None
    top_k: int
    rag_enabled: bool


class NoteCreateRequest(BaseModel):
    title: str
    content: str
    folder: str | None = None
    tags: list[str] | None = None


class RelatedNoteItem(BaseModel):
    title: str
    source_path: str
    score: float


class NoteCreateResponse(BaseModel):
    path: str
    related: list[RelatedNoteItem]
