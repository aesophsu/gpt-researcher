import unittest

from gpt_researcher.skills.researcher import ResearchConductor


class _Cfg:
    max_search_results_per_query = 7
    retriever_priority_mode = "staged"
    medical_time_window_years = 5
    tavily_efficiency_mode = True
    tavily_soft_fallback = True
    domain_tier0 = "tier0.org,tier0b.org"
    domain_tier1 = "tier1.org"
    domain_tier2 = "tier2.org"
    min_unique_sources = 8
    rerank_explain_log_mode = "json"
    rerank_explain_scope = 10


class _JsonHandler:
    def __init__(self):
        self.events = []

    def log_event(self, event_type, data):
        self.events.append({"type": event_type, "data": data})


class _Researcher:
    def __init__(self, retrievers):
        self.retrievers = retrievers
        self.cfg = _Cfg()
        self.visited_urls = set()
        self.verbose = False
        self.websocket = None


class PubMedRetriever:
    def __init__(self, query, query_domains=None):
        self.query = query
        self.query_domains = query_domains or []

    def search(self, max_results=10):
        return [
            {
                "href": "https://pubmed.ncbi.nlm.nih.gov/1",
                "title": "Randomized trial in cardiology",
                "body": "systematic review 2025 doi 10.1000/xyz123",
            },
            {
                "href": "https://pubmed.ncbi.nlm.nih.gov/2",
                "title": "Clinical guideline update",
                "body": "guideline cohort 2024",
            },
            {
                "href": "https://pubmed.ncbi.nlm.nih.gov/3",
                "title": "Meta-analysis",
                "body": "meta-analysis 2023",
            },
            {
                "href": "https://pubmed.ncbi.nlm.nih.gov/4",
                "title": "Trial methods",
                "body": "randomized 2022",
            },
        ][:max_results]


class SemanticRetriever:
    def __init__(self, query, query_domains=None):
        self.query = query
        self.query_domains = query_domains or []

    def search(self, max_results=10):
        return [
            {"href": "https://semanticscholar.org/paper/1", "title": "Paper 1", "body": "cohort 2024"},
            {"href": "https://semanticscholar.org/paper/2", "title": "Paper 2", "body": "open access 2021"},
            {"href": "https://semanticscholar.org/paper/3", "title": "Paper 3", "body": "general"},
        ][:max_results]


class TavilyRetriever:
    calls = []

    def __init__(self, query, query_domains=None):
        self.query = query
        self.query_domains = query_domains or []

    def search(self, max_results=10):
        TavilyRetriever.calls.append(
            {
                "query_domains": list(self.query_domains),
                "max_results": max_results,
                "query": self.query,
            }
        )
        domains_key = ",".join(self.query_domains)
        if "tier0.org" in domains_key:
            return [
                {"href": "https://tier0.org/a", "title": "Tier0 A", "body": "medical evidence 2024"},
                {"href": "https://tier0b.org/b", "title": "Tier0 B", "body": "medical evidence 2023"},
            ][:max_results]
        if "tier1.org" in domains_key:
            return [
                {"href": "https://tier1.org/c", "title": "Tier1 C", "body": "clinical 2023"},
                {"href": "https://tier1.org/d", "title": "Tier1 D", "body": "clinical 2022"},
                {"href": "https://tier1.org/e", "title": "Tier1 E", "body": "clinical 2021"},
            ][:max_results]
        return []


class TestStagedRetrieval(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        TavilyRetriever.calls = []

    async def test_skips_tavily_when_academic_results_sufficient(self):
        cfg = _Cfg()
        cfg.min_unique_sources = 6
        researcher = _Researcher([PubMedRetriever, SemanticRetriever, TavilyRetriever])
        researcher.cfg = cfg
        conductor = ResearchConductor(researcher)

        urls = await conductor._search_relevant_source_urls("hypertension treatment")

        self.assertGreaterEqual(len(urls), 6)
        self.assertEqual(len(TavilyRetriever.calls), 0)
        self.assertIn("pubmed.ncbi.nlm.nih.gov", urls[0])

    async def test_tavily_soft_fallback_uses_tiers_and_dynamic_max(self):
        class SparsePubMedRetriever(PubMedRetriever):
            def search(self, max_results=10):
                return super().search(max_results=2)

        class SparseSemanticRetriever(SemanticRetriever):
            def search(self, max_results=10):
                return super().search(max_results=1)

        researcher = _Researcher([SparsePubMedRetriever, SparseSemanticRetriever, TavilyRetriever])
        conductor = ResearchConductor(researcher)

        urls = await conductor._search_relevant_source_urls("heart failure management")

        self.assertGreaterEqual(len(urls), 8)
        self.assertGreaterEqual(len(TavilyRetriever.calls), 2)
        self.assertEqual(TavilyRetriever.calls[0]["query_domains"], ["tier0.org", "tier0b.org"])
        self.assertEqual(TavilyRetriever.calls[1]["query_domains"], ["tier1.org"])
        self.assertLessEqual(TavilyRetriever.calls[0]["max_results"], researcher.cfg.max_search_results_per_query)

    async def test_staged_output_has_normalized_shape(self):
        researcher = _Researcher([PubMedRetriever, SemanticRetriever, TavilyRetriever])
        conductor = ResearchConductor(researcher)
        normalized = await conductor._search_with_retriever(PubMedRetriever, "hypertension treatment", [], 2)

        self.assertEqual(len(normalized), 2)
        first = normalized[0]
        self.assertTrue(hasattr(first, "url"))
        self.assertTrue(hasattr(first, "title"))
        self.assertTrue(hasattr(first, "snippet"))
        self.assertTrue(hasattr(first, "source"))
        self.assertTrue(hasattr(first, "score_breakdown"))
        self.assertTrue(hasattr(first, "raw"))

    async def test_top10_explain_event_written(self):
        class SparsePubMedRetriever(PubMedRetriever):
            def search(self, max_results=10):
                return super().search(max_results=2)

        class SparseSemanticRetriever(SemanticRetriever):
            def search(self, max_results=10):
                return super().search(max_results=1)

        researcher = _Researcher([SparsePubMedRetriever, SparseSemanticRetriever, TavilyRetriever])
        conductor = ResearchConductor(researcher)
        conductor.json_handler = _JsonHandler()

        _ = await conductor._search_relevant_source_urls("heart failure management")

        self.assertGreaterEqual(len(conductor.json_handler.events), 1)
        explain_events = [e for e in conductor.json_handler.events if e["type"] == "retrieval_rerank_explain"]
        self.assertGreaterEqual(len(explain_events), 1)
        latest = explain_events[-1]["data"]
        self.assertIn("results", latest)
        self.assertLessEqual(latest["top_n"], 10)


if __name__ == "__main__":
    unittest.main()
