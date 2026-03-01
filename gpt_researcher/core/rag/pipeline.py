from __future__ import annotations

from dataclasses import dataclass

from gpt_researcher.core.documents import ChunkPolicy, DefaultChunker, DefaultMetadataExtractor
from gpt_researcher.core.documents.types import RawDocument
from gpt_researcher.core.storage.ports import IndexStorePort, VectorStorePort

from .ports import RetrievalPipelinePort
from .types import IngestResult, RetrievalHit


@dataclass
class IndexedChunk:
    chunk_id: str
    collection_name: str
    source: str
    page: int | None
    text: str
    title: str | None
    doi: str | None
    year: int | None
    journal: str | None
    external_metadata_matched: bool = False

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "collection_name": self.collection_name,
            "source": self.source,
            "page": self.page,
            "text": self.text,
            "title": self.title,
            "doi": self.doi,
            "year": self.year,
            "journal": self.journal,
            "external_metadata_matched": self.external_metadata_matched,
        }


class DefaultRetrievalPipeline(RetrievalPipelinePort):
    def __init__(self, index_store: IndexStorePort, vector_store: VectorStorePort):
        self._index_store = index_store
        self._vector_store = vector_store
        self._chunker = DefaultChunker()
        self._meta = DefaultMetadataExtractor()

    async def ingest(self, docs: list[RawDocument], namespace: str) -> IngestResult:
        docs_summary: list[dict] = []
        chunks: list[IndexedChunk] = []

        for doc in docs:
            meta = self._meta.extract(doc)
            docs_summary.append(
                {
                    "doc_id": doc.source,
                    "source": doc.source,
                    "title": meta.title,
                    "year": meta.year,
                    "doi": meta.doi,
                    "pages": 1,
                    "external_metadata_matched": False,
                    "journal": meta.journal,
                }
            )

            for c in self._chunker.chunk(doc, ChunkPolicy()):
                chunks.append(
                    IndexedChunk(
                        chunk_id=c.chunk_id,
                        collection_name=namespace,
                        source=c.source,
                        page=c.page,
                        text=c.text,
                        title=meta.title,
                        doi=meta.doi,
                        year=meta.year,
                        journal=meta.journal,
                        external_metadata_matched=False,
                    )
                )

        existing = self._index_store.get_collection(namespace)
        merged_docs = (existing.get("docs") or []) + docs_summary
        merged_chunks = (existing.get("chunks") or []) + chunks

        warnings: list[str] = []
        if self._vector_store.enabled:
            _, warnings = self._vector_store.upsert_chunks(namespace, chunks)
        else:
            warnings.append("vector_store_disabled")

        self._index_store.upsert_collection(namespace, merged_docs, merged_chunks)
        return IngestResult(indexed_docs=len(docs_summary), chunks=len(chunks), warnings=warnings)

    async def search(
        self,
        query: str,
        namespace: str,
        top_k: int,
        filters: dict | None = None,
    ) -> list[RetrievalHit]:
        _ = filters
        results = self._vector_store.search(namespace, query, top_k)
        if results:
            return [
                RetrievalHit(
                    source=getattr(item, "source", "local"),
                    snippet=getattr(item, "snippet", ""),
                    score=float(getattr(item, "score", 0.0)),
                    metadata={
                        "title": getattr(item, "title", None),
                        "page": getattr(item, "page", None),
                        "doi": getattr(item, "doi", None),
                        "year": getattr(item, "year", None),
                        "journal": getattr(item, "journal", None),
                    },
                )
                for item in results
            ]

        collection = self._index_store.get_collection(namespace)
        chunks = collection.get("chunks") if isinstance(collection, dict) else []
        fallback = []
        for chunk in (chunks or [])[:top_k]:
            if not isinstance(chunk, dict):
                continue
            snippet = str(chunk.get("text") or "")
            fallback.append(
                RetrievalHit(
                    source=str(chunk.get("source") or "local"),
                    snippet=snippet[:500],
                    score=0.2,
                    metadata={
                        "title": chunk.get("title"),
                        "page": chunk.get("page"),
                        "doi": chunk.get("doi"),
                        "year": chunk.get("year"),
                        "journal": chunk.get("journal"),
                    },
                )
            )
        return fallback
