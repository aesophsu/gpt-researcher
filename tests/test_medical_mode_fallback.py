import unittest

from backend.server import websocket_manager
from gpt_researcher.utils.enum import Tone


class _DummyLogsHandler:
    last_instance = None

    def __init__(self, websocket, task):
        self.events = []
        _DummyLogsHandler.last_instance = self

    async def send_json(self, data):
        self.events.append(data)


class _DummyBasicReport:
    def __init__(self, **kwargs):
        self.gpt_researcher = type(
            "DummyResearcher",
            (),
            {"visited_urls": {"https://pubmed.ncbi.nlm.nih.gov/2"}},
        )()

    async def run(self):
        return "fallback report"


class TestMedicalModeFallback(unittest.IsolatedAsyncioTestCase):
    async def test_medical_mode_qdrant_failure_falls_back(self):
        async def failing_medical_search(request):
            raise RuntimeError("qdrant unavailable")

        original_logs = websocket_manager.CustomLogsHandler
        original_basic = websocket_manager.BasicReport
        original_medical = websocket_manager.medical_search
        try:
            websocket_manager.CustomLogsHandler = _DummyLogsHandler
            websocket_manager.BasicReport = _DummyBasicReport
            websocket_manager.medical_search = failing_medical_search

            report = await websocket_manager.run_agent(
                task="重症胰腺炎治疗",
                report_type="research_report",
                report_source="hybrid",
                source_urls=[],
                document_urls=[],
                tone=Tone.Objective,
                websocket=None,
                medical_mode=True,
            )
        finally:
            websocket_manager.CustomLogsHandler = original_logs
            websocket_manager.BasicReport = original_basic
            websocket_manager.medical_search = original_medical

        self.assertEqual(report, "fallback report")
        stats_event = next(e for e in _DummyLogsHandler.last_instance.events if e.get("content") == "medical_retrieval_stats")
        self.assertTrue(stats_event["metadata"]["fallback_to_academic"])


if __name__ == "__main__":
    unittest.main()
