from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class FileStorage(ABC):
    """Where uploaded bytes land before ingestion. Local now; an
    S3-compatible implementation later means writing one new class, not
    touching the upload endpoint or anything downstream of it."""

    @abstractmethod
    def save(self, filename: str, content: bytes) -> Path: ...


class LocalFileStorage(FileStorage):
    def __init__(self, base_dir: Path):
        self._base_dir = base_dir

    def save(self, filename: str, content: bytes) -> Path:
        self._base_dir.mkdir(parents=True, exist_ok=True)
        dest = self._base_dir / filename
        dest.write_bytes(content)
        return dest
