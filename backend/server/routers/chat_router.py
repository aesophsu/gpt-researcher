from __future__ import annotations

import logging

from fastapi import APIRouter

from ..dependencies import get_dependencies
from ..models import ChatRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
async def chat(chat_request: ChatRequest):
    try:
        return await get_dependencies().chat_service.process(chat_request)
    except Exception as e:
        logger.error(f"Error processing chat request: {str(e)}", exc_info=True)
        return {"error": str(e)}
