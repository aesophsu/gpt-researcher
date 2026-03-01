from __future__ import annotations

import time
from typing import Any, Dict

from ..models import ReportRecord
from ..repositories.report_repository import ReportRepository


class ReportService:
    def __init__(self, repository: ReportRepository):
        self._repository = repository

    async def list_reports(self, report_ids: str | None) -> list[Dict[str, Any]]:
        report_ids_list = report_ids.split(",") if report_ids else None
        reports = await self._repository.list(report_ids_list)
        return [self._normalize_report(r) for r in reports]

    async def get_report_or_none(self, research_id: str) -> Dict[str, Any] | None:
        report = await self._repository.get(research_id)
        if report is None:
            return None
        return self._normalize_report(report)

    async def create_or_update_report(self, data: Dict[str, Any]) -> str:
        research_id = data.get("id", "temp_id")

        now_ms = int(time.time() * 1000)
        existing = await self._repository.get(research_id)
        incoming_timestamp = data.get("timestamp")
        timestamp = incoming_timestamp if isinstance(incoming_timestamp, int) else now_ms
        if existing and isinstance(existing.get("timestamp"), int):
            timestamp = max(timestamp, existing["timestamp"])

        report = {
            "id": research_id,
            "question": data.get("question"),
            "answer": data.get("answer"),
            "orderedData": data.get("orderedData") or [],
            "chatMessages": data.get("chatMessages") or [],
            "timestamp": timestamp,
        }
        await self._repository.upsert(research_id, report)
        return research_id

    async def update_report(self, research_id: str, data: Dict[str, Any]) -> bool:
        existing = await self._repository.get(research_id)
        if existing is None:
            return False

        now_ms = int(time.time() * 1000)
        updated = {
            **existing,
            **{k: v for k, v in data.items() if v is not None},
            "id": research_id,
            "timestamp": now_ms,
        }
        await self._repository.upsert(research_id, updated)
        return True

    async def delete_report(self, research_id: str) -> bool:
        return await self._repository.delete(research_id)

    async def get_chat_messages(self, research_id: str) -> list[Dict[str, Any]] | None:
        report = await self._repository.get(research_id)
        if report is None:
            return None
        return report.get("chatMessages") or []

    async def add_chat_message(self, research_id: str, message: Dict[str, Any]) -> bool:
        report = await self._repository.get(research_id)
        if report is None:
            return False

        chat_messages = report.get("chatMessages") or []
        if isinstance(chat_messages, list):
            chat_messages = [*chat_messages, message]
        else:
            chat_messages = [message]

        now_ms = int(time.time() * 1000)
        updated = {
            **report,
            "chatMessages": chat_messages,
            "timestamp": now_ms,
        }
        await self._repository.upsert(research_id, updated)
        return True

    def _normalize_report(self, report: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "id": report.get("id", "temp_id"),
            "question": report.get("question"),
            "answer": report.get("answer"),
            "orderedData": report.get("orderedData") or [],
            "chatMessages": report.get("chatMessages") or [],
            "timestamp": report.get("timestamp") if isinstance(report.get("timestamp"), int) else int(time.time() * 1000),
        }
        return ReportRecord(**payload).model_dump()
