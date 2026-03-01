from __future__ import annotations

from typing import Protocol

from .types import Chunk, ChunkPolicy, DocumentMetadata, DocumentSource, RawDocument


class DocumentLoaderPort(Protocol):
    async def load(self, source: DocumentSource) -> list[RawDocument]:
        ...


class ChunkerPort(Protocol):
    def chunk(self, doc: RawDocument, policy: ChunkPolicy) -> list[Chunk]:
        ...


class MetadataExtractorPort(Protocol):
    def extract(self, doc: RawDocument) -> DocumentMetadata:
        ...
