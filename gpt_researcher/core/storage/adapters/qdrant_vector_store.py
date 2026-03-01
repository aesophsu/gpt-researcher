from __future__ import annotations


class QdrantVectorStoreAdapter:
    """Lazy adapter to backend MedicalVectorStore to avoid import-time coupling."""

    def __init__(self) -> None:
        from backend.server.medical_vector_store import MedicalVectorStore

        self._impl = MedicalVectorStore()

    @property
    def enabled(self) -> bool:
        return self._impl.enabled

    def healthy(self) -> bool:
        return self._impl.healthy()

    def upsert_chunks(self, collection_name: str, chunks: list):
        return self._impl.upsert_chunks(collection_name, chunks)

    def search(self, collection_name: str, query: str, top_k: int):
        return self._impl.search(collection_name, query, top_k)
