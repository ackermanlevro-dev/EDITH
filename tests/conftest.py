from __future__ import annotations

import pytest_asyncio

from backend.config.settings import Settings
from backend.container import AppContext, build_context


@pytest_asyncio.fixture
async def ctx() -> AppContext:
    """Runs against TEST_DATABASE_URL (a separate database on the same
    container), never DATABASE_URL - tests must not compete against, or be
    diluted by, whatever real content is actually indexed."""
    settings = Settings()
    if not settings.test_database_url:
        raise RuntimeError("TEST_DATABASE_URL is not set - see .env.example")
    test_settings = settings.model_copy(update={"database_url": settings.test_database_url})

    context = await build_context(test_settings)
    yield context
    await context.close()


@pytest_asyncio.fixture
async def clean_documents(ctx: AppContext):
    """Tests append the source_path(s) they create; everything in the list
    gets deleted (cascading to chunks) after the test, regardless of outcome -
    keeps the real knowledge index free of test fixtures."""
    created_paths: list[str] = []
    yield created_paths
    if created_paths:
        await ctx.pool.execute(
            "DELETE FROM documents WHERE source_path = ANY($1::text[])", created_paths
        )
