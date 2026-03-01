import inspect

from backend.report_type.detailed_report import detailed_report as detailed_report_module
from backend.server import websocket_manager


def test_websocket_manager_defaults_are_immutable():
    start_streaming_signature = inspect.signature(websocket_manager.WebSocketManager.start_streaming)
    run_agent_signature = inspect.signature(websocket_manager.run_agent)

    assert start_streaming_signature.parameters["query_domains"].default is None
    assert start_streaming_signature.parameters["mcp_configs"].default is None
    assert run_agent_signature.parameters["query_domains"].default is None
    assert run_agent_signature.parameters["mcp_configs"].default is None


def test_detailed_report_list_inputs_are_instance_isolated(monkeypatch):
    class DummyResearcher:
        def __init__(self, **kwargs):
            self.visited_urls = set()
            self.context = []
            self.agent = None
            self.role = None
            self.mcp_configs = kwargs.get("mcp_configs")
            self.mcp_strategy = kwargs.get("mcp_strategy")

    monkeypatch.setattr(detailed_report_module, "GPTResearcher", DummyResearcher)

    first = detailed_report_module.DetailedReport(
        query="q1",
        report_type="research_report",
        report_source="web",
    )
    second = detailed_report_module.DetailedReport(
        query="q2",
        report_type="research_report",
        report_source="web",
    )

    first.source_urls.append("https://example.com/a")
    first.document_urls.append("https://example.com/doc")
    first.query_domains.append("example.com")
    first.subtopics.append({"task": "foo"})

    assert second.source_urls == []
    assert second.document_urls == []
    assert second.query_domains == []
    assert second.subtopics == []
