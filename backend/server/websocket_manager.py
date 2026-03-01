import asyncio
import logging
from typing import Any, Dict, List

from fastapi import WebSocket

from backend.report_type import BasicReport, DetailedReport
from gpt_researcher.utils.enum import Tone
from .application.research_orchestrator import (
    medical_local_topk,
    resolve_medical_collection,
    run_research,
)
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
    return resolve_medical_collection(requested_collection)


def _medical_local_topk() -> int:
    return medical_local_topk()


async def run_agent(
    task: str,
    report_type: str,
    report_source: str,
    source_urls: list[str] | None,
    document_urls: list[str] | None,
    tone: Tone,
    websocket,
    stream_output=None,
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
    _ = stream_output
    return await run_research(
        task=task,
        report_type=report_type,
        report_source=report_source,
        source_urls=source_urls,
        document_urls=document_urls,
        tone=tone,
        websocket=websocket,
        headers=headers,
        query_domains=query_domains,
        config_path=config_path,
        return_researcher=return_researcher,
        mcp_enabled=mcp_enabled,
        mcp_strategy=mcp_strategy,
        mcp_configs=mcp_configs,
        medical_mode=medical_mode,
        medical_collection=medical_collection,
        logs_handler_cls=CustomLogsHandler,
        basic_report_cls=BasicReport,
        detailed_report_cls=DetailedReport,
        medical_search_fn=medical_search,
    )
