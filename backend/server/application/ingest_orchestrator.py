from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from gpt_researcher.core.documents import list_files


@dataclass
class IngestPlan:
    base_path: Path
    recursive: bool
    collection_name: str


class IngestOrchestrator:
    """Coordinates ingest plans while delegating domain-specific indexing strategy."""

    def build_plan(self, doc_path: str, recursive: bool, collection_name: str) -> IngestPlan:
        return IngestPlan(
            base_path=Path(doc_path).expanduser().resolve(),
            recursive=recursive,
            collection_name=collection_name,
        )

    def discover_files(self, plan: IngestPlan) -> list[Path]:
        return list_files(plan.base_path, plan.recursive)

    async def run(
        self,
        plan: IngestPlan,
        worker: Callable[..., Awaitable[Any]],
        **kwargs: Any,
    ) -> Any:
        files = self.discover_files(plan)
        return await worker(files=files, collection_name=plan.collection_name, **kwargs)
