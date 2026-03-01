from __future__ import annotations

from typing import Protocol

from gpt_researcher.core.documents.types import RawDocument

from .types import IngestResult, RetrievalHit


class RetrievalPipelinePort(Protocol):
    async def ingest(self, docs: list[RawDocument], namespace: str) -> IngestResult:
        ...

    async def search(
        self,
        query: str,
        namespace: str,
        top_k: int,
        filters: dict | None = None,
    ) -> list[RetrievalHit]:
        ...
