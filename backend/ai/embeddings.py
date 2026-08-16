from __future__ import annotations

from abc import ABC, abstractmethod

import httpx


class EmbeddingProvider(ABC):
    """Abstraction over an embedding model - deliberately separate from
    LLMProvider, since the chat model and the embedding model are configured
    and swapped independently."""

    dimension: int

    @abstractmethod
    async def embed(self, text: str) -> list[float]: ...

    async def close(self) -> None:
        """Only meaningful for providers holding a persistent connection."""


class OllamaEmbeddingProvider(EmbeddingProvider):
    def __init__(self, base_url: str, model: str, dimension: int, timeout: float = 60.0):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self.dimension = dimension
        # Reused for the process lifetime - see the same note in ai/llm.py.
        self._client = httpx.AsyncClient(timeout=timeout)

    async def embed(self, text: str) -> list[float]:
        resp = await self._client.post(
            f"{self._base_url}/api/embeddings",
            json={"model": self._model, "prompt": text},
        )
        resp.raise_for_status()
        vector = resp.json()["embedding"]

        if len(vector) != self.dimension:
            raise ValueError(
                f"Embedding provider returned {len(vector)}-dim vectors, but "
                f"EMBEDDING_DIMENSION is configured as {self.dimension}. The "
                "embedding model probably changed - update EMBEDDING_DIMENSION "
                "and rebuild the vector column/index in database/schema.sql."
            )
        return vector

    async def close(self) -> None:
        await self._client.aclose()


def build_embedding_provider(
    provider: str, *, base_url: str, model: str, dimension: int
) -> EmbeddingProvider:
    if provider == "ollama":
        return OllamaEmbeddingProvider(base_url=base_url, model=model, dimension=dimension)
    raise ValueError(f"Unknown embedding provider: {provider!r}")
