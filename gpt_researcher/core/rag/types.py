from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RetrievalHit:
    source: str
    snippet: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class IngestResult:
    indexed_docs: int
    chunks: int
    warnings: list[str] = field(default_factory=list)
