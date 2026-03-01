import asyncio

import pytest

from backend.server.clarification_gate import ClarificationGateManager
from gpt_researcher.skills.researcher import ResearchConductor


class DummyWebsocket:
    def __init__(self, response):
        self.response = response
        self.called = False
        self.kwargs = None

    async def await_clarification_request(self, **kwargs):
        self.called = True
        self.kwargs = kwargs
        return self.response

    async def send_json(self, payload):
        return None


class DummyResearcher:
    def __init__(self, websocket):
        self.websocket = websocket
        self.report_type = "research_report"
        self.kwargs = {}


@pytest.mark.asyncio
async def test_clarification_gate_manager_resolve():
    manager = ClarificationGateManager()
    session_id = "session-1"
    request_id = "req-1"
    payload = {"request_id": request_id, "approved_subqueries": ["a"]}

    future = await manager.register(session_id, request_id)
    resolved = await manager.resolve(session_id, request_id, payload)
    assert resolved is True

    result = await asyncio.wait_for(future, timeout=0.2)
    assert result == payload

    await manager.unregister(session_id, request_id)


@pytest.mark.asyncio
async def test_clarification_applies_subqueries_and_constraints(monkeypatch):
    monkeypatch.setenv("ENABLE_CLARIFICATION_GATE", "true")

    ws = DummyWebsocket(
        {
            "request_id": "abc",
            "approved_subqueries": ["  first  ", "second", "first"],
            "constraints": {
                "scope": "example.com, https://www.docs.python.org/",
                "time_window": "2024-2026",
                "language": "Chinese",
                "output_preference": "Executive summary first",
            },
            "notes": "focus on official docs",
        }
    )
    conductor = ResearchConductor(DummyResearcher(ws))

    subqueries, domains = await conductor._await_clarification_if_needed(
        query="test query",
        sub_queries=["one", "two"],
        query_domains=["openai.com"],
    )

    assert ws.called is True
    assert subqueries == ["first", "second"]
    assert "openai.com" in domains
    assert "example.com" in domains
    assert "docs.python.org" in domains
    assert conductor.researcher.kwargs["response_language"] == "Chinese"
    assert conductor.researcher.kwargs["output_preference"] == "Executive summary first"


@pytest.mark.asyncio
async def test_clarification_rejects_empty_subqueries(monkeypatch):
    monkeypatch.setenv("ENABLE_CLARIFICATION_GATE", "true")
    ws = DummyWebsocket(
        {
            "request_id": "abc",
            "approved_subqueries": [" ", ""],
            "constraints": {},
            "notes": None,
        }
    )
    conductor = ResearchConductor(DummyResearcher(ws))

    with pytest.raises(ValueError, match="at least one approved sub-query"):
        await conductor._await_clarification_if_needed(
            query="test query",
            sub_queries=["one"],
            query_domains=[],
        )
