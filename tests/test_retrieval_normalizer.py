import unittest

from gpt_researcher.skills.researcher import NormalizedResult, ResearchConductor


class _Cfg:
    max_search_results_per_query = 7
    retriever_priority_mode = "staged"
    medical_time_window_years = 5
    tavily_efficiency_mode = True
    tavily_soft_fallback = True
    domain_tier0 = "pubmed.ncbi.nlm.nih.gov,ncbi.nlm.nih.gov"
    domain_tier1 = "who.int"
    domain_tier2 = ""
    min_unique_sources = 8
    rerank_explain_log_mode = "json"
    rerank_explain_scope = 10


class _JsonHandler:
    def __init__(self):
        self.events = []

    def log_event(self, event_type, data):
        self.events.append({"type": event_type, "data": data})


class _Researcher:
    def __init__(self):
        self.cfg = _Cfg()
        self.retrievers = []
        self.visited_urls = set()
        self.verbose = False
        self.websocket = None


class TestRetrievalNormalizer(unittest.TestCase):
    def setUp(self):
        self.researcher = _Researcher()
        self.conductor = ResearchConductor(self.researcher)
        self.conductor.json_handler = _JsonHandler()

    def test_normalize_pubmed_fields_complete(self):
        item = {
            "url": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12345/",
            "title": "Randomized Clinical Trial in Hypertension",
            "raw_content": "Guideline update. 2025. DOI 10.1000/abc123.",
        }
        result = self.conductor._normalize_result(item, "pubmed", "hypertension treatment")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.source, "pubmed")
        self.assertEqual(result.open_access, True)
        self.assertIsNotNone(result.doi)
        self.assertEqual(result.evidence_type, "guideline")
        self.assertIsInstance(result.raw, dict)

    def test_normalize_semantic_fields_complete(self):
        item = {
            "href": "https://semanticscholar.org/paper/123",
            "title": "Systematic review of diabetes treatment",
            "body": "This systematic review (2024) compares outcomes.",
            "year": 2024,
            "venue": "Diabetes Care",
            "isOpenAccess": True,
        }
        result = self.conductor._normalize_result(item, "semantic", "diabetes")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.source, "semantic")
        self.assertEqual(result.journal, "Diabetes Care")
        self.assertEqual(result.evidence_type, "systematic_review")
        self.assertEqual(result.open_access, True)

    def test_normalize_tavily_fields_complete(self):
        item = {
            "href": "https://who.int/news-room/fact-sheets",
            "title": "WHO guideline summary",
            "body": "Latest guideline statements and recommendations 2023",
        }
        result = self.conductor._normalize_result(item, "tavily", "public health guideline")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.source, "tavily")
        self.assertEqual(result.domain, "who.int")
        self.assertEqual(result.evidence_type, "guideline")

    def test_dedupe_prefers_higher_score_and_academic_source(self):
        a = NormalizedResult(
            url="https://example.org/a",
            title="A",
            snippet="randomized trial",
            source="tavily",
            source_rank_weight=0.65,
            doi="10.1000/x1",
            domain="example.org",
            raw={},
            final_score=0.9,
            raw_score=0.9,
        )
        b = NormalizedResult(
            url="https://example.org/b",
            title="B",
            snippet="randomized trial",
            source="pubmed",
            source_rank_weight=1.0,
            doi="10.1000/x1",
            domain="pubmed.ncbi.nlm.nih.gov",
            raw={},
            final_score=0.88,
            raw_score=0.88,
        )
        deduped = self.conductor._dedupe_results([a, b])
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0].source, "pubmed")

    def test_score_breakdown_contains_all_components(self):
        result = NormalizedResult(
            url="https://pubmed.ncbi.nlm.nih.gov/123",
            title="Meta-analysis in hypertension",
            snippet="Systematic review and meta-analysis from 2024. DOI 10.1000/xyz777",
            source="pubmed",
            source_rank_weight=1.0,
            year=2024,
            doi="10.1000/xyz777",
            journal="NEJM",
            evidence_type="meta_analysis",
            domain="pubmed.ncbi.nlm.nih.gov",
            raw={},
        )
        breakdown = self.conductor._compute_score_breakdown("hypertension meta analysis", result)
        expected = {
            "source_weight",
            "query_overlap",
            "doi_bonus",
            "evidence_type_bonus",
            "recency_bonus",
            "domain_trust_bonus",
            "low_quality_penalty",
        }
        self.assertEqual(set(breakdown.keys()), expected)

    def test_explain_scope_limits_to_top10(self):
        results = []
        for i in range(12):
            results.append(
                NormalizedResult(
                    url=f"https://pubmed.ncbi.nlm.nih.gov/{i}",
                    title=f"Title {i}",
                    snippet=f"randomized 2024 doi 10.1000/test{i}",
                    source="pubmed",
                    source_rank_weight=1.0,
                    year=2024,
                    doi=f"10.1000/test{i}",
                    evidence_type="rct",
                    domain="pubmed.ncbi.nlm.nih.gov",
                    raw={},
                )
            )
        ranked = self.conductor._apply_rerank("hypertension randomized trial", results)
        self.conductor._emit_rerank_logs(
            query="hypertension randomized trial",
            mode="staged",
            candidates_total=12,
            deduped_total=12,
            ranked=ranked,
        )
        event = self.conductor.json_handler.events[-1]
        self.assertEqual(event["type"], "retrieval_rerank_explain")
        self.assertEqual(event["data"]["top_n"], 10)
        self.assertEqual(len(event["data"]["results"]), 10)


if __name__ == "__main__":
    unittest.main()
