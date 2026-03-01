from __future__ import annotations

from typing import Any, Protocol


class JobStorePort(Protocol):
    async def create_job(self, job_id: str, job_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        ...

    async def set_running(self, job_id: str) -> None:
        ...

    async def update_progress(self, job_id: str, **progress_patch: Any) -> None:
        ...

    async def set_completed(self, job_id: str, result: dict[str, Any]) -> None:
        ...

    async def set_failed(self, job_id: str, error: str) -> None:
        ...

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        ...
