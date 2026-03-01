from __future__ import annotations

from typing import Any, Dict, List

from ..storage.base import ReportStorage


class ReportRepository:
    def __init__(self, storage: ReportStorage):
        self._storage = storage

    async def list(self, report_ids: List[str] | None = None) -> List[Dict[str, Any]]:
        return await self._storage.list_reports(report_ids)

    async def get(self, report_id: str) -> Dict[str, Any] | None:
        return await self._storage.get_report(report_id)

    async def upsert(self, report_id: str, report: Dict[str, Any]) -> None:
        await self._storage.upsert_report(report_id, report)

    async def delete(self, report_id: str) -> bool:
        return await self._storage.delete_report(report_id)
