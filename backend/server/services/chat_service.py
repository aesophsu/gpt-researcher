from __future__ import annotations

import json
import logging
import time

from ...chat.chat import ChatAgentWithMemory

from ..models import ChatRequest

logger = logging.getLogger(__name__)


class ChatService:
    async def process(self, chat_request: ChatRequest) -> dict:
        logger.info(f"Received chat request with {len(chat_request.messages)} messages")

        chat_agent = ChatAgentWithMemory(
            report=chat_request.report,
            config_path="default",
            headers=None,
        )

        response_content, tool_calls_metadata = await chat_agent.chat(chat_request.messages, None)
        logger.info(f"response_content: {response_content}")
        logger.info(f"Got chat response of length: {len(response_content) if response_content else 0}")

        if tool_calls_metadata:
            logger.info(f"Tool calls used: {json.dumps(tool_calls_metadata)}")

        response_message = {
            "role": "assistant",
            "content": response_content,
            "timestamp": int(time.time() * 1000),
            "metadata": {"tool_calls": tool_calls_metadata} if tool_calls_metadata else None,
        }
        return {"response": response_message}
