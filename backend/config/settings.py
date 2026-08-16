from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central config. Every knob the spec asked for is here and nowhere else -
    no model names, providers, or paths hardcoded elsewhere in the app."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"

    database_url: str
    test_database_url: str | None = None

    llm_provider: str = "ollama"
    llm_model: str = "qwen2.5:1.5b-instruct"
    ollama_base_url: str = "http://localhost:11434"

    embedding_provider: str = "ollama"
    embedding_model: str = "nomic-embed-text"
    embedding_dimension: int = 768

    obsidian_vault_path: str | None = None
    # Comma-separated; blank means "use the built-in defaults" (see
    # backend/ingestion/sources.py DEFAULT_IGNORE_PATTERNS) rather than
    # indexing everything - never index secrets or VCS/dependency internals.
    obsidian_ignore_patterns: str = ""

    rag_enabled: bool = True
    chunk_size: int = 1000
    chunk_overlap: int = 150
    top_k: int = 5

    web_search_enabled: bool = False
    cloud_llm_enabled: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
