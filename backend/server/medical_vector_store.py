from __future__ import annotations

import logging
import os
import re
from hashlib import sha1
from typing import Any, Iterable

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models
except Exception:  # pragma: no cover - dependency may be optional at runtime before install
    QdrantClient = None
    models = None

from gpt_researcher.config.config import Config
from gpt_researcher.memory import Memory
from .medical_models import MedicalSearchResult

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "default"


class MedicalVectorStore:
    def __init__(self) -> None:
        self.backend = os.getenv("MEDICAL_VECTOR_BACKEND", "qdrant").strip().lower()
        self.force_disabled = _env_bool("QDRANT_FORCE_DISABLED", default=False)

        self.qdrant_url = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
        self.qdrant_api_key = os.getenv("QDRANT_API_KEY", "")
        self.collection_prefix = os.getenv("QDRANT_COLLECTION_PREFIX", "medical_")
        self.prefer_grpc = _env_bool("QDRANT_PREFER_GRPC", default=False)
        self.timeout_seconds = int(os.getenv("QDRANT_TIMEOUT_SECONDS", "10"))

        self._enabled = self.backend == "qdrant" and not self.force_disabled
        self._client: QdrantClient | None = None
        self._embeddings = None

        if self._enabled and (QdrantClient is None or models is None):
            logger.warning("Qdrant dependencies are not available. Falling back to JSON backend.")
            self._enabled = False

        if self._enabled:
            self._client = QdrantClient(
                url=self.qdrant_url,
                api_key=self.qdrant_api_key or None,
                prefer_grpc=self.prefer_grpc,
                timeout=self.timeout_seconds,
            )

            cfg = Config(config_path="default")
            self._embeddings = Memory(
                cfg.embedding_provider,
                cfg.embedding_model,
                **cfg.embedding_kwargs,
            ).get_embeddings()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _collection_name(self, collection_name: str) -> str:
        return f"{self.collection_prefix}{_slugify(collection_name)}"

    def healthy(self) -> bool:
        if not self.enabled or self._client is None:
            return False

        try:
            self._client.get_collections()
            return True
        except Exception as exc:
            logger.warning("Qdrant health check failed: %s", exc)
            return False

    def _ensure_collection(self, collection_name: str, vector_size: int) -> None:
        assert self._client is not None
        if self._client.collection_exists(collection_name=collection_name):
            return
        self._client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(
                size=vector_size,
                distance=models.Distance.COSINE,
            ),
        )

    def upsert_chunks(self, collection_name: str, chunks: Iterable[Any]) -> tuple[int, list[str]]:
        if not self.enabled or self._client is None or self._embeddings is None:
            return 0, ["qdrant_disabled"]

        chunk_list = list(chunks)
        if not chunk_list:
            return 0, []

        warnings: list[str] = []
        texts = [getattr(chunk, "text", "") for chunk in chunk_list]
        vectors = self._embeddings.embed_documents(texts)

        if not vectors:
            return 0, ["empty_vectors"]

        qdrant_collection = self._collection_name(collection_name)
        self._ensure_collection(qdrant_collection, vector_size=len(vectors[0]))

        points: list[models.PointStruct] = []
        for idx, (chunk, vector) in enumerate(zip(chunk_list, vectors, strict=False)):
            point_id = idx + 1
            chunk_id = str(getattr(chunk, "chunk_id", point_id))
            payload = {
                "chunk_id": chunk_id,
                "collection_name": getattr(chunk, "collection_name", collection_name),
                "source": getattr(chunk, "source", ""),
                "page": getattr(chunk, "page", None),
                "title": getattr(chunk, "title", None),
                "doi": getattr(chunk, "doi", None),
                "year": getattr(chunk, "year", None),
                "journal": getattr(chunk, "journal", None),
                "external_metadata_matched": getattr(chunk, "external_metadata_matched", False),
                "text": getattr(chunk, "text", ""),
            }
            # Use stable uint64 id to support idempotent upsert.
            stable_id = int(sha1(f"{qdrant_collection}:{chunk_id}".encode("utf-8")).hexdigest()[:16], 16)
            points.append(models.PointStruct(id=stable_id, vector=vector, payload=payload))

        self._client.upsert(collection_name=qdrant_collection, points=points, wait=True)
        return len(points), warnings

    def search(self, collection_name: str, query: str, top_k: int) -> list[MedicalSearchResult]:
        if not self.enabled or self._client is None or self._embeddings is None:
            return []

        qdrant_collection = self._collection_name(collection_name)
        if not self._client.collection_exists(collection_name=qdrant_collection):
            return []

        query_vector = self._embeddings.embed_query(query)
        hits = self._client.search(
            collection_name=qdrant_collection,
            query_vector=query_vector,
            limit=top_k,
            with_payload=True,
        )

        results: list[MedicalSearchResult] = []
        for hit in hits:
            payload = hit.payload or {}
            text = str(payload.get("text") or "")
            results.append(
                MedicalSearchResult(
                    source_type="local",
                    source=str(payload.get("source") or "local"),
                    title=payload.get("title"),
                    snippet=text[:500],
                    score=round(float(hit.score or 0.0), 4),
                    page=payload.get("page"),
                    doi=payload.get("doi"),
                    year=payload.get("year"),
                    journal=payload.get("journal"),
                )
            )
        return results
