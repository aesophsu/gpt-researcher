import pytest

from gpt_researcher.core.documents import RawDocument
from gpt_researcher.core.rag import DefaultRetrievalPipeline
from gpt_researcher.core.storage.adapters import JsonIndexStoreAdapter


class _DisabledVectorStore:
    enabled = False

    def healthy(self):
        return False

    def upsert_chunks(self, collection_name, chunks):
        _ = collection_name, chunks
        return 0, ["disabled"]

    def search(self, collection_name, query, top_k):
        _ = collection_name, query, top_k
        return []


@pytest.mark.asyncio
async def test_rag_pipeline_ingest_and_search_fallback(tmp_path):
    index_store = JsonIndexStoreAdapter(tmp_path / "index.json")
    pipeline = DefaultRetrievalPipeline(index_store=index_store, vector_store=_DisabledVectorStore())

    docs = [RawDocument(source="doc1", raw_content="hypertension guideline 2025 DOI 10.1000/x")]
    res = await pipeline.ingest(docs, namespace="med")
    assert res.indexed_docs == 1
    assert res.chunks >= 1

    hits = await pipeline.search(query="hypertension", namespace="med", top_k=3)
    assert len(hits) >= 1
    assert "hypertension" in hits[0].snippet.lower()
