from __future__ import annotations

import asyncpg
from pgvector.asyncpg import register_vector


async def create_pool(database_url: str) -> asyncpg.Pool:
    async def _init(conn: asyncpg.Connection) -> None:
        await register_vector(conn)

    return await asyncpg.create_pool(database_url, init=_init, min_size=1, max_size=5)
