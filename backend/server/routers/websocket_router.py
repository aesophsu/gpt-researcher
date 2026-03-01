from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..dependencies import get_dependencies
from ..server_utils import handle_websocket_communication

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ws"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    manager = get_dependencies().manager
    await manager.connect(websocket)
    try:
        await handle_websocket_communication(websocket, manager)
    except WebSocketDisconnect as e:
        logger.info(f"WebSocket disconnected with code {e.code} and reason: '{e.reason}'")
        await manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"Unexpected WebSocket error: {str(e)}")
        await manager.disconnect(websocket)
