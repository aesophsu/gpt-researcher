from __future__ import annotations

import logging
import os
from typing import Any

from gpt_researcher.actions import stream_output
from gpt_researcher.utils.enum import ReportType, Tone
from backend.report_type import BasicReport, DetailedReport

from ..medical_models import MedicalSearchRequest
from ..medical_service import medical_search
from ..server_utils import CustomLogsHandler

logger = logging.getLogger(__name__)


def resolve_medical_collection(requested_collection: str | None) -> str:
    if requested_collection:
        return requested_collection
    return os.getenv("MEDICAL_DEFAULT_COLLECTION") or os.getenv("ZOTERO_QDRANT_COLLECTION") or "default"


def medical_local_topk() -> int:
    raw = os.getenv("MEDICAL_LOCAL_TOPK", "8")
    try:
        value = int(raw)
    except ValueError:
        value = 8
    return max(3, min(20, value))


async def run_research(
    task: str,
    report_type: str,
    report_source: str,
    source_urls: list[str] | None,
    document_urls: list[str] | None,
    tone: Tone,
    websocket,
    headers=None,
    query_domains: list[str] | None = None,
    config_path: str = "",
    return_researcher: bool = False,
    mcp_enabled: bool = False,
    mcp_strategy: str = "fast",
    mcp_configs: list[dict[str, Any]] | None = None,
    medical_mode: bool = False,
    medical_collection=None,
    logs_handler_cls=CustomLogsHandler,
    basic_report_cls=BasicReport,
    detailed_report_cls=DetailedReport,
    medical_search_fn=medical_search,
):
    source_urls = source_urls or []
    document_urls = document_urls or []
    query_domains = query_domains or []
    mcp_configs = mcp_configs or []

    logs_handler = logs_handler_cls(websocket, task)

    if mcp_enabled and mcp_configs:
        logger.info("MCP enabled with strategy '%s' and %d server(s)", mcp_strategy, len(mcp_configs))
        await logs_handler.send_json(
            {
                "type": "logs",
                "content": "mcp_init",
                "output": f"🔧 MCP enabled with strategy '{mcp_strategy}' and {len(mcp_configs)} server(s)",
            }
        )

    local_hits = 0
    fallback_to_academic = False
    resolved_collection = resolve_medical_collection(medical_collection) if medical_mode else None
    medical_seed_documents = []

    if medical_mode:
        await logs_handler.send_json(
            {
                "type": "logs",
                "content": "medical_retrieval_stage_local",
                "output": f"🩺 Medical mode enabled: searching local Qdrant collection '{resolved_collection}' first...",
                "metadata": {
                    "collection": resolved_collection,
                    "top_k": medical_local_topk(),
                },
            }
        )
        try:
            local_response = await medical_search_fn(
                MedicalSearchRequest(
                    query=task,
                    top_k=medical_local_topk(),
                    sources="local",
                    collection_name=resolved_collection,
                )
            )
            local_results = local_response.results or []
            local_hits = len(local_results)
            medical_seed_documents = [
                {
                    "title": item.title or f"Local evidence #{idx + 1}",
                    "url": item.url or f"local://{item.source}/{idx + 1}",
                    "raw_content": item.snippet or "",
                    "source_type": item.source_type,
                    "source": item.source,
                    "score": item.score,
                    "doi": item.doi,
                    "year": item.year,
                    "journal": item.journal,
                }
                for idx, item in enumerate(local_results)
                if (item.snippet or "").strip()
            ]
        except Exception as exc:
            fallback_to_academic = True
            logger.warning("medical mode local retrieval failed: %s", exc)
            await logs_handler.send_json(
                {
                    "type": "logs",
                    "content": "medical_retrieval_stage_local",
                    "output": "⚠️ Local Qdrant retrieval failed, falling back to academic retrieval.",
                    "metadata": {
                        "collection": resolved_collection,
                        "error": type(exc).__name__,
                    },
                }
            )

    common_kwargs = {
        "medical_mode": medical_mode,
        "medical_collection": resolved_collection,
        "medical_seed_documents": medical_seed_documents,
    }

    if report_type == "multi_agents":
        from multi_agents.main import run_research_task

        report = await run_research_task(
            query=task,
            websocket=logs_handler,
            stream_output=stream_output,
            tone=tone,
            headers=headers,
        )
        report = report.get("report", "")

    elif report_type == ReportType.DetailedReport.value:
        researcher = detailed_report_cls(
            query=task,
            query_domains=query_domains,
            report_type=report_type,
            report_source=report_source,
            source_urls=source_urls,
            document_urls=document_urls,
            tone=tone,
            config_path=config_path,
            websocket=logs_handler,
            headers=headers,
            mcp_configs=mcp_configs if mcp_enabled else None,
            mcp_strategy=mcp_strategy if mcp_enabled else None,
            **common_kwargs,
        )
        report = await researcher.run()
    else:
        researcher = basic_report_cls(
            query=task,
            query_domains=query_domains,
            report_type=report_type,
            report_source=report_source,
            source_urls=source_urls,
            document_urls=document_urls,
            tone=tone,
            config_path=config_path,
            websocket=logs_handler,
            headers=headers,
            mcp_configs=mcp_configs if mcp_enabled else None,
            mcp_strategy=mcp_strategy if mcp_enabled else None,
            **common_kwargs,
        )
        report = await researcher.run()

    if medical_mode and report_type != "multi_agents":
        academic_hits = len(getattr(researcher.gpt_researcher, "visited_urls", set()))
        if local_hits == 0:
            fallback_to_academic = True
        await logs_handler.send_json(
            {
                "type": "logs",
                "content": "medical_retrieval_stats",
                "output": (
                    f"📊 Medical retrieval stats - Local(Qdrant): {local_hits}, "
                    f"Academic: {academic_hits}, Fallback: {'Yes' if fallback_to_academic else 'No'}"
                ),
                "metadata": {
                    "local_hits": local_hits,
                    "academic_hits": academic_hits,
                    "fallback_to_academic": fallback_to_academic,
                    "collection": resolved_collection,
                },
            }
        )

    if report_type != "multi_agents" and return_researcher:
        return report, researcher.gpt_researcher
    return report
