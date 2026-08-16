from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx


@dataclass
class LLMResponse:
    text: str
    model: str


class LLMProvider(ABC):
    """Abstraction over a chat/completion model. RAG and the API talk only to
    this interface, never to Ollama directly - swapping models or adding a
    cloud provider later means writing one new class, not touching callers."""

    @abstractmethod
    async def generate(self, prompt: str, *, system: str | None = None) -> LLMResponse: ...

    async def close(self) -> None:
        """Only meaningful for providers holding a persistent connection."""


class OllamaLLMProvider(LLMProvider):
    def __init__(self, base_url: str, model: str, timeout: float = 120.0):
        self._base_url = base_url.rstrip("/")
        self._model = model
        # One client reused for the process lifetime, not "async with
        # httpx.AsyncClient()" per call - that was paying TCP connection
        # setup/teardown to localhost on every single request, real overhead
        # on a CPU this constrained even though the destination is local.
        self._client = httpx.AsyncClient(timeout=timeout)

    async def generate(self, prompt: str, *, system: str | None = None) -> LLMResponse:
        payload: dict = {"model": self._model, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system

        resp = await self._client.post(f"{self._base_url}/api/generate", json=payload)
        resp.raise_for_status()
        data = resp.json()

        return LLMResponse(text=data["response"], model=self._model)

    async def close(self) -> None:
        await self._client.aclose()


def build_llm_provider(provider: str, *, base_url: str, model: str) -> LLMProvider:
    if provider == "ollama":
        return OllamaLLMProvider(base_url=base_url, model=model)
    raise ValueError(f"Unknown LLM provider: {provider!r}")
