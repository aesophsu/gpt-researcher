import asyncio
import datetime
import json
import logging
import os
import traceback
from typing import Any, Dict, List

from fastapi import WebSocket

from report_type import BasicReport, DetailedReport

from gpt_researcher.utils.enum import ReportType, Tone
from gpt_researcher.actions import stream_output  # Import stream_output
from .medical_models import MedicalSearchRequest
from .medical_service import medical_search
from .server_utils import CustomLogsHandler

logger = logging.getLogger(__name__)

class WebSocketManager:
    """Manage websockets"""

    def __init__(self):
        """Initialize the WebSocketManager class."""
        self.active_connections: List[WebSocket] = []
        self.sender_tasks: Dict[WebSocket, asyncio.Task] = {}
        self.message_queues: Dict[WebSocket, asyncio.Queue] = {}

    async def start_sender(self, websocket: WebSocket):
        """Start the sender task."""
        queue = self.message_queues.get(websocket)
        if not queue:
            return

        while True:
            try:
                message = await queue.get()
                if message is None:  # Shutdown signal
                    break
                    
                if websocket in self.active_connections:
                    if message == "ping":
                        await websocket.send_text("pong")
                    else:
                        await websocket.send_text(message)
                else:
                    break
            except Exception as e:
                print(f"Error in sender task: {e}")
                break

    async def connect(self, websocket: WebSocket):
        """Connect a websocket."""
        try:
            await websocket.accept()
            self.active_connections.append(websocket)
            self.message_queues[websocket] = asyncio.Queue()
            self.sender_tasks[websocket] = asyncio.create_task(
                self.start_sender(websocket))
        except Exception as e:
            print(f"Error connecting websocket: {e}")
            if websocket in self.active_connections:
                await self.disconnect(websocket)

    async def disconnect(self, websocket: WebSocket):
        """Disconnect a websocket."""
        try:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
                
                # Cancel sender task if it exists
                if websocket in self.sender_tasks:
                    try:
                        self.sender_tasks[websocket].cancel()
                        await self.message_queues[websocket].put(None)
                    except Exception as e:
                        logger.error(f"Error canceling sender task: {e}")
                    finally:
                        # Always try to clean up regardless of errors
                        if websocket in self.sender_tasks:
                            del self.sender_tasks[websocket]
                
                # Clean up message queue
                if websocket in self.message_queues:
                    del self.message_queues[websocket]
                
                # Finally close the WebSocket
                try:
                    await websocket.close()
                except Exception as e:
                    logger.info(f"WebSocket already closed: {e}")
        except Exception as e:
            logger.error(f"Error during WebSocket disconnection: {e}")
            # Still try to close the connection if possible
            try:
                await websocket.close()
            except:
                pass  # If this fails too, there's nothing more we can do

    async def start_streaming(self, task, report_type, report_source, source_urls, document_urls, tone, websocket, headers=None, query_domains=None, mcp_enabled=False, mcp_strategy="fast", mcp_configs=None, medical_mode=False, medical_collection=None):
        """Start streaming the output."""
        query_domains = query_domains or []
        mcp_configs = mcp_configs or []
        tone = Tone[tone]
        # add customized JSON config file path here
        config_path = "default"

        # Pass MCP parameters to run_agent
        report = await run_agent(
            task, report_type, report_source, source_urls, document_urls, tone, websocket, 
            headers=headers, query_domains=query_domains, config_path=config_path,
            mcp_enabled=mcp_enabled, mcp_strategy=mcp_strategy, mcp_configs=mcp_configs,
            medical_mode=medical_mode, medical_collection=medical_collection
        )
        return report

def _resolve_medical_collection(requested_collection: str | None) -> str:
    if requested_collection:
        return requested_collection
    return (
        os.getenv("MEDICAL_DEFAULT_COLLECTION")
        or os.getenv("ZOTERO_QDRANT_COLLECTION")
        or "default"
    )


def _medical_local_topk() -> int:
    raw = os.getenv("MEDICAL_LOCAL_TOPK", "8")
    try:
        value = int(raw)
    except ValueError:
        value = 8
    return max(3, min(20, value))


async def run_agent(
    task: str,
    report_type: str,
    report_source: str,
    source_urls: list[str] | None,
    document_urls: list[str] | None,
    tone: Tone,
    websocket,
    stream_output=stream_output,
    headers=None,
    query_domains: list[str] | None = None,
    config_path: str = "",
    return_researcher: bool = False,
    mcp_enabled: bool = False,
    mcp_strategy: str = "fast",
    mcp_configs: list[dict[str, Any]] | None = None,
    medical_mode: bool = False,
    medical_collection=None,
):
    """Run a research agent and return report text (or report + researcher).

    Args:
        task: User task prompt to research.
        report_type: Selected report mode.
        report_source: Report source type.
        source_urls: Optional source URLs for grounding.
        document_urls: Optional document URLs for grounding.
        tone: Report tone enum.
        websocket: Optional websocket used for streaming logs.
        stream_output: Stream callback passed to multi-agent flow.
        headers: Optional request headers for upstream providers.
        query_domains: Optional domain allowlist for search.
        config_path: Configuration profile path.
        return_researcher: If True, return `(report, researcher)`.
        mcp_enabled: Enables MCP for this request.
        mcp_strategy: MCP strategy ("fast", "deep", "disabled").
        mcp_configs: Optional MCP server configuration list.
        medical_mode: Whether to run staged medical retrieval mode.
        medical_collection: Optional medical collection override.

    Returns:
        `str` report, or `(str, researcher)` when `return_researcher` is True.

    Notes:
        This function does not mutate process-wide environment variables.
        MCP/retriever behavior is resolved by GPTResearcher configuration.
    """
    source_urls = source_urls or []
    document_urls = document_urls or []
    query_domains = query_domains or []
    mcp_configs = mcp_configs or []

    # Create logs handler for this research task
    logs_handler = CustomLogsHandler(websocket, task)

    # Set up MCP configuration if enabled
    if mcp_enabled and mcp_configs:
        logger.info(
            "MCP enabled with strategy '%s' and %d server(s)",
            mcp_strategy,
            len(mcp_configs),
        )
        await logs_handler.send_json({
            "type": "logs",
            "content": "mcp_init",
            "output": f"🔧 MCP enabled with strategy '{mcp_strategy}' and {len(mcp_configs)} server(s)"
        })

    local_hits = 0
    fallback_to_academic = False
    resolved_collection = _resolve_medical_collection(medical_collection) if medical_mode else None
    medical_seed_documents = []

    if medical_mode:
        await logs_handler.send_json({
            "type": "logs",
            "content": "medical_retrieval_stage_local",
            "output": f"🩺 Medical mode enabled: searching local Qdrant collection '{resolved_collection}' first...",
            "metadata": {
                "collection": resolved_collection,
                "top_k": _medical_local_topk(),
            },
        })
        try:
            local_response = await medical_search(
                MedicalSearchRequest(
                    query=task,
                    top_k=_medical_local_topk(),
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
            await logs_handler.send_json({
                "type": "logs",
                "content": "medical_retrieval_stage_local",
                "output": "⚠️ Local Qdrant retrieval failed, falling back to academic retrieval.",
                "metadata": {
                    "collection": resolved_collection,
                    "error": type(exc).__name__,
                },
            })

    common_kwargs = {
        "medical_mode": medical_mode,
        "medical_collection": resolved_collection,
        "medical_seed_documents": medical_seed_documents,
    }

    # Initialize researcher based on report type
    if report_type == "multi_agents":
        report = await run_research_task(
            query=task, 
            websocket=logs_handler,  # Use logs_handler instead of raw websocket
            stream_output=stream_output, 
            tone=tone, 
            headers=headers
        )
        report = report.get("report", "")

    elif report_type == ReportType.DetailedReport.value:
        researcher = DetailedReport(
            query=task,
            query_domains=query_domains,
            report_type=report_type,
            report_source=report_source,
            source_urls=source_urls,
            document_urls=document_urls,
            tone=tone,
            config_path=config_path,
            websocket=logs_handler,  # Use logs_handler instead of raw websocket
            headers=headers,
            mcp_configs=mcp_configs if mcp_enabled else None,
            mcp_strategy=mcp_strategy if mcp_enabled else None,
            **common_kwargs,
        )
        report = await researcher.run()
        
    else:
        researcher = BasicReport(
            query=task,
            query_domains=query_domains,
            report_type=report_type,
            report_source=report_source,
            source_urls=source_urls,
            document_urls=document_urls,
            tone=tone,
            config_path=config_path,
            websocket=logs_handler,  # Use logs_handler instead of raw websocket
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
        await logs_handler.send_json({
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
        })

    if report_type != "multi_agents" and return_researcher:
        return report, researcher.gpt_researcher
    else:
        return report
