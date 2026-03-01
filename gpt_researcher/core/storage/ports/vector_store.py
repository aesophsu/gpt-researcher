from __future__ import annotations

from typing import Any, Protocol


class VectorStorePort(Protocol):
    @property
    def enabled(self) -> bool:
        ...

    def healthy(self) -> bool:
        ...

    def upsert_chunks(self, collection_name: str, chunks: list[Any]) -> tuple[int, list[str]]:
        ...

    def search(self, collection_name: str, query: str, top_k: int) -> list[Any]:
        ...
