from __future__ import annotations

from typing import Any, Dict, List, Protocol


class ReportStorage(Protocol):
    async def list_reports(self, report_ids: List[str] | None = None) -> List[Dict[str, Any]]:
        ...

    async def get_report(self, report_id: str) -> Dict[str, Any] | None:
        ...

    async def upsert_report(self, report_id: str, report: Dict[str, Any]) -> None:
        ...

    async def delete_report(self, report_id: str) -> bool:
        ...
