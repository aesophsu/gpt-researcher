import unittest

from gpt_researcher.skills.researcher import ResearchConductor


class _PromptFamily:
    @staticmethod
    def join_local_web_documents(local_context, web_context):
        return f"{local_context}\n---\n{web_context}"


class _ContextManager:
    async def get_similar_content_by_query(self, query, pages):
        return "local_seed_context"


class _Researcher:
    def __init__(self):
        self.medical_seed_documents = [
            {"raw_content": "local evidence", "url": "local://chunk/1", "title": "Local Evidence"}
        ]
        self.context_manager = _ContextManager()
        self.prompt_family = _PromptFamily()


class TestResearcherMedicalSeed(unittest.IsolatedAsyncioTestCase):
    async def test_medical_seed_context_combines_with_academic(self):
        researcher = _Researcher()
        conductor = ResearchConductor(researcher)

        async def fake_web_search(query, scraped_data=None, query_domains=None):
            return "academic_context"

        conductor._get_context_by_web_search = fake_web_search

        combined = await conductor._get_context_with_medical_seed("重症胰腺炎", [])
        self.assertIn("local_seed_context", combined)
        self.assertIn("academic_context", combined)

    async def test_medical_seed_empty_returns_academic_only(self):
        researcher = _Researcher()
        researcher.medical_seed_documents = []
        conductor = ResearchConductor(researcher)

        async def fake_web_search(query, scraped_data=None, query_domains=None):
            return "academic_only"

        conductor._get_context_by_web_search = fake_web_search

        combined = await conductor._get_context_with_medical_seed("重症胰腺炎", [])
        self.assertEqual(combined, "academic_only")


if __name__ == "__main__":
    unittest.main()
