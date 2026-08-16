from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import asyncpg

from backend.ai.embeddings import EmbeddingProvider, build_embedding_provider
from backend.ai.llm import LLMProvider, build_llm_provider
from backend.config.database import create_pool
from backend.config.settings import Settings
from backend.documents.repository import DocumentRepository
from backend.ingestion.pipeline import IngestionPipeline
from backend.notes.writer import NoteWriter
from backend.rag.generation import AnswerGenerator
from backend.rag.router import QueryRouter
from backend.storage.file_storage import FileStorage, LocalFileStorage


@dataclass
class AppContext:
    """Everything wired together once, from Settings. The API's lifespan hook
    and the CLI both build one of these instead of duplicating the wiring."""

    settings: Settings
    pool: asyncpg.Pool
    repository: DocumentRepository
    llm: LLMProvider
    embeddings: EmbeddingProvider
    pipeline: IngestionPipeline
    generator: AnswerGenerator
    notes: NoteWriter | None  # None when OBSIDIAN_VAULT_PATH isn't configured
    file_storage: FileStorage

    async def close(self) -> None:
        await self.llm.close()
        await self.embeddings.close()
        await self.pool.close()


async def build_context(settings: Settings) -> AppContext:
    pool = await create_pool(settings.database_url)
    repository = DocumentRepository(pool)

    llm = build_llm_provider(
        settings.llm_provider, base_url=settings.ollama_base_url, model=settings.llm_model
    )
    embeddings = build_embedding_provider(
        settings.embedding_provider,
        base_url=settings.ollama_base_url,
        model=settings.embedding_model,
        dimension=settings.embedding_dimension,
    )

    pipeline = IngestionPipeline(
        repository, embeddings, settings.chunk_size, settings.chunk_overlap
    )
    generator = AnswerGenerator(llm, embeddings, repository, QueryRouter(), top_k=settings.top_k)

    notes = None
    if settings.obsidian_vault_path:
        notes = NoteWriter(Path(settings.obsidian_vault_path), repository, embeddings, pipeline)

    file_storage = LocalFileStorage(Path(settings.upload_dir))

    return AppContext(
        settings=settings,
        pool=pool,
        repository=repository,
        llm=llm,
        embeddings=embeddings,
        pipeline=pipeline,
        generator=generator,
        notes=notes,
        file_storage=file_storage,
    )
