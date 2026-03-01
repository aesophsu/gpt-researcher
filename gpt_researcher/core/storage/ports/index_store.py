from __future__ import annotations

from typing import Any, Protocol


class IndexStorePort(Protocol):
    def upsert_collection(self, collection_name: str, docs: list[dict[str, Any]], chunks: list[Any]) -> None:
        ...

    def get_collection(self, collection_name: str) -> dict[str, Any]:
        ...
