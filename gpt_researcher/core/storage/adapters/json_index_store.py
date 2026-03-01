from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..ports import IndexStorePort


class JsonIndexStoreAdapter(IndexStorePort):
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"collections": {}}
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "collections" in data:
                return data
        except Exception:
            pass
        return {"collections": {}}

    def _save(self) -> None:
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(self._state, f, ensure_ascii=True, indent=2)

    def upsert_collection(self, collection_name: str, docs: list[dict[str, Any]], chunks: list[Any]) -> None:
        serialized_chunks: list[dict[str, Any]] = []
        for chunk in chunks:
            if hasattr(chunk, "to_dict"):
                serialized_chunks.append(chunk.to_dict())
            elif isinstance(chunk, dict):
                serialized_chunks.append(chunk)
            else:
                serialized_chunks.append(getattr(chunk, "__dict__", {}))
        self._state["collections"][collection_name] = {
            "docs": docs,
            "chunks": serialized_chunks,
        }
        self._save()

    def get_collection(self, collection_name: str) -> dict[str, Any]:
        return self._state["collections"].get(collection_name, {"docs": [], "chunks": []})
