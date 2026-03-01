import asyncio
import os
import sys

import pytest

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
backend_path = os.path.join(project_root, "backend")
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from server.clarification_gate import clarification_gate_manager
from server.server_utils import handle_clarification_response


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_handle_clarification_response_routes_by_request_id():
    ws = FakeWebSocket()
    session_id = str(id(ws))
    request_id = "req-42"
    future = await clarification_gate_manager.register(session_id, request_id)

    await handle_clarification_response(
        ws,
        f'clarification_response {{"request_id":"{request_id}","approved_subqueries":["a"],"constraints":{{"scope":null,"time_window":null,"language":null,"output_preference":null}},"notes":null}}',
    )

    result = await asyncio.wait_for(future, timeout=0.2)
    assert result["request_id"] == request_id
    assert any(item.get("content") == "clarification_received" for item in ws.sent)
    await clarification_gate_manager.unregister(session_id, request_id)


@pytest.mark.asyncio
async def test_handle_clarification_response_missing_request_id():
    ws = FakeWebSocket()
    await handle_clarification_response(ws, 'clarification_response {"approved_subqueries":["a"]}')
    assert any(item.get("content") == "clarification_error" for item in ws.sent)
