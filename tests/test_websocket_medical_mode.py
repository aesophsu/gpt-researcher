import unittest

from backend.server import websocket_manager
from backend.server.medical_models import MedicalSearchResponse, MedicalSearchResult
from backend.server.server_utils import extract_command_data
from gpt_researcher.utils.enum import Tone


class _DummyLogsHandler:
    last_instance = None

    def __init__(self, websocket, task):
        self.websocket = websocket
        self.task = task
        self.events = []
        _DummyLogsHandler.last_instance = self

    async def send_json(self, data):
        self.events.append(data)


class _DummyBasicReport:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.gpt_researcher = type(
            "DummyResearcher",
            (),
            {
                "visited_urls": {"https://pubmed.ncbi.nlm.nih.gov/1"},
                "medical_mode": kwargs.get("medical_mode", False),
                "medical_collection": kwargs.get("medical_collection"),
                "medical_seed_documents": kwargs.get("medical_seed_documents", []),
            },
        )()

    async def run(self):
        return "dummy report"


class TestWebSocketMedicalMode(unittest.IsolatedAsyncioTestCase):
    def test_extract_command_data_includes_medical_fields(self):
        payload = {
            "task": "query",
            "report_type": "research_report",
            "report_source": "hybrid",
            "tone": "Objective",
            "medical_mode": True,
            "medical_collection": "zotero_med",
        }
        values = extract_command_data(payload)
        self.assertTrue(values[-2])
        self.assertEqual(values[-1], "zotero_med")

    async def test_run_agent_medical_mode_local_stage_first(self):
        async def fake_medical_search(request):
            return MedicalSearchResponse(
                query=request.query,
                expanded_query=request.query,
                results=[
                    MedicalSearchResult(
                        source_type="local",
                        source="qdrant_local",
                        title="Local evidence",
                        snippet="severe acute pancreatitis guideline evidence",
                        score=0.91,
                    )
                ],
            )

        original_logs = websocket_manager.CustomLogsHandler
        original_basic = websocket_manager.BasicReport
        original_medical = websocket_manager.medical_search
        try:
            websocket_manager.CustomLogsHandler = _DummyLogsHandler
            websocket_manager.BasicReport = _DummyBasicReport
            websocket_manager.medical_search = fake_medical_search

            report = await websocket_manager.run_agent(
                task="重症胰腺炎",
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

        self.assertEqual(report, "dummy report")
        events = _DummyLogsHandler.last_instance.events
        stage_index = next(i for i, e in enumerate(events) if e.get("content") == "medical_retrieval_stage_local")
        stats_index = next(i for i, e in enumerate(events) if e.get("content") == "medical_retrieval_stats")
        self.assertLess(stage_index, stats_index)
        self.assertEqual(events[stats_index]["metadata"]["local_hits"], 1)


if __name__ == "__main__":
    unittest.main()
