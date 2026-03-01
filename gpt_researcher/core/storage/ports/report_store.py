from __future__ import annotations

from typing import Any, Protocol


class ReportStorePort(Protocol):
    async def list_reports(self, report_ids: list[str] | None = None) -> list[dict[str, Any]]:
        ...

    async def get_report(self, report_id: str) -> dict[str, Any] | None:
        ...

    async def upsert_report(self, report_id: str, report: dict[str, Any]) -> None:
        ...

    async def delete_report(self, report_id: str) -> bool:
        ...
