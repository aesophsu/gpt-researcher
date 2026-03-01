from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DocumentSource:
    path: str | list[str]
    recursive: bool = True


@dataclass
class RawDocument:
    source: str
    raw_content: str
    section: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChunkPolicy:
    chunk_size: int = 1200
    overlap: int = 150


@dataclass
class Chunk:
    chunk_id: str
    source: str
    text: str
    page: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentMetadata:
    title: str | None = None
    year: int | None = None
    doi: str | None = None
    journal: str | None = None
