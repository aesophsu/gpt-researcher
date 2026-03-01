from .chat_router import router as chat_router
from .frontend_router import router as frontend_router
from .report_router import router as report_router
from .research_router import router as research_router
from .websocket_router import router as websocket_router

__all__ = [
    "chat_router",
    "frontend_router",
    "report_router",
    "research_router",
    "websocket_router",
]
