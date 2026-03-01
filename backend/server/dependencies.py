from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .repositories.report_repository import ReportRepository
from .services.chat_service import ChatService
from .services.report_service import ReportService
from .services.research_service import ResearchService
from .storage.json_report_storage import JsonReportStorage
from .websocket_manager import WebSocketManager


@dataclass
class AppDependencies:
    manager: WebSocketManager
    report_service: ReportService
    research_service: ResearchService
    chat_service: ChatService
    frontend_dir: Path


_deps: AppDependencies | None = None


def init_dependencies(report_store_path: Path, doc_path: str, frontend_dir: Path) -> AppDependencies:
    global _deps
    manager = WebSocketManager()
    storage = JsonReportStorage(report_store_path)
    repository = ReportRepository(storage)
    report_service = ReportService(repository)
    research_service = ResearchService(manager=manager, doc_path=doc_path)
    chat_service = ChatService()

    _deps = AppDependencies(
        manager=manager,
        report_service=report_service,
        research_service=research_service,
        chat_service=chat_service,
        frontend_dir=frontend_dir,
    )
    return _deps


def get_dependencies() -> AppDependencies:
    if _deps is None:
        raise RuntimeError("Dependencies are not initialized")
    return _deps
