import asyncio
from dataclasses import dataclass

from fastapi.testclient import TestClient

from backend.server.app import app
from backend.server import medical_service
from backend.server.medical_models import MedicalPolishRequest, MedicalSearchResponse, MedicalSearchResult


client = TestClient(app)


def test_medical_ingest_and_local_search(tmp_path, monkeypatch):
    index_file = tmp_path / "medical_index.json"
    monkeypatch.setenv("MEDICAL_INDEX_PATH", str(index_file))
    monkeypatch.setenv("QDRANT_FORCE_DISABLED", "true")

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "paper1.txt").write_text(
        "Hypertension treatment improves blood pressure control in adults. PMID example 2024.",
        encoding="utf-8",
    )

    ingest_resp = client.post(
        "/api/v1/medical/ingest",
        json={"doc_path": str(docs_dir), "collection_name": "med", "recursive": True},
    )
    assert ingest_resp.status_code == 200
    ingest_data = ingest_resp.json()
    assert ingest_data["indexed_docs"] >= 1
    assert ingest_data["chunks"] >= 1

    search_resp = client.post(
        "/api/v1/medical/search",
        json={"query": "high blood pressure treatment", "top_k": 5, "sources": "local", "collection_name": "med"},
    )
    assert search_resp.status_code == 200
    search_data = search_resp.json()
    assert search_data["results"]
    assert search_data["results"][0]["source_type"] == "local"


def test_medical_polish_fallback_without_llm(tmp_path, monkeypatch):
    index_file = tmp_path / "medical_index.json"
    monkeypatch.setenv("MEDICAL_INDEX_PATH", str(index_file))
    monkeypatch.setenv("QDRANT_FORCE_DISABLED", "true")

    for key in [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
    ]:
        monkeypatch.delenv(key, raising=False)

    resp = client.post(
        "/api/v1/medical/polish",
        json={
            "text": "This intervention significantly reduces mortality in severe cases.",
            "mode": "academic",
            "require_evidence": False,
            "strict_fact_mode": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["revisions"]) >= 1
    assert "llm_not_configured" in data["risk_flags"]


def test_citation_audit_detects_missing_and_mixed_style(monkeypatch):
    monkeypatch.delenv("MEDICAL_INDEX_PATH", raising=False)
    manuscript = (
        "The treatment significantly improves outcomes in ICU patients. "
        "Previous trial reported benefit [1]. "
        "Another analysis confirmed this (Smith, 2022)."
    )

    resp = client.post(
        "/api/v1/medical/citation-audit",
        json={"manuscript_text": manuscript, "format": "vancouver"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert any("Mixed citation styles" in issue for issue in data["format_issues"])
    assert any(item["sentence_id"] == "s1" for item in data["missing_citations"])
    assert "consistency_score" in data


def test_zotero_ingest_with_json_and_bibtex(tmp_path, monkeypatch):
    index_file = tmp_path / "medical_index.json"
    monkeypatch.setenv("MEDICAL_INDEX_PATH", str(index_file))
    monkeypatch.setenv("QDRANT_FORCE_DISABLED", "true")

    pdf_dir = tmp_path / "zotero_pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    (pdf_dir / "smith2024-hypertension.txt").write_text(
        "Local full text content. Hypertension outcomes were improved in trial populations.",
        encoding="utf-8",
    )

    zotero_json = tmp_path / "zotero.json"
    zotero_json.write_text(
        """
[
  {
    "title": "Hypertension outcomes in trial populations",
    "DOI": "10.1000/hyper.2024.10",
    "date": "2024-08-02",
    "attachments": [{"path": "smith2024-hypertension.txt"}]
  }
]
        """.strip(),
        encoding="utf-8",
    )

    bib_file = tmp_path / "library.bib"
    bib_file.write_text(
        """
@article{smith2024,
  title={Hypertension outcomes in trial populations},
  year={2024},
  doi={10.1000/hyper.2024.10}
}
        """.strip(),
        encoding="utf-8",
    )

    resp = client.post(
        "/api/v1/medical/zotero-ingest",
        json={
            "collection_name": "zotero-med",
            "pdf_dir": str(pdf_dir),
            "zotero_json_path": str(zotero_json),
            "bibtex_path": str(bib_file),
            "recursive": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["indexed_docs"] == 1
    assert data["match_stats"]["pdf_files"] == 1
    assert data["match_stats"]["json_entries"] == 1
    assert data["match_stats"]["bib_entries"] == 1
    assert data["match_stats"]["matched_metadata"] >= 1


def test_citation_audit_unmatched_and_unused_references(monkeypatch):
    monkeypatch.delenv("MEDICAL_INDEX_PATH", raising=False)
    manuscript = (
        "Treatment significantly reduces mortality [2]. "
        "Additional claim suggests benefit [5]."
    )
    references = [
        "[1] Johnson et al. Critical care outcomes. 2021.",
        "[2] Smith et al. Randomized ICU trial. 2022.",
    ]

    resp = client.post(
        "/api/v1/medical/citation-audit",
        json={"manuscript_text": manuscript, "format": "vancouver", "references": references},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert any("not found" in item["reason"] for item in data["unmatched_citations"])
    assert any(line.startswith("[1]") for line in data["unused_references"])
    assert isinstance(data["consistency_score"], float)


def test_local_search_rerank_with_doi_year_and_journal(tmp_path, monkeypatch):
    index_file = tmp_path / "medical_index.json"
    monkeypatch.setenv("MEDICAL_INDEX_PATH", str(index_file))
    monkeypatch.setenv("QDRANT_FORCE_DISABLED", "true")

    pdf_dir = tmp_path / "papers"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    (pdf_dir / "older-study.txt").write_text(
        "Clinical outcomes discussed generally for blood pressure control.",
        encoding="utf-8",
    )
    (pdf_dir / "smith2024-hypertension.txt").write_text(
        "This trial reports blood pressure outcomes and intervention effects.",
        encoding="utf-8",
    )

    zotero_json = tmp_path / "zotero.json"
    zotero_json.write_text(
        """
[
  {
    "title": "Hypertension trial outcomes",
    "DOI": "10.1000/hyper.2024.10",
    "date": "2024",
    "publicationTitle": "New England Journal of Medicine",
    "attachments": [{"path": "smith2024-hypertension.txt"}]
  }
]
        """.strip(),
        encoding="utf-8",
    )

    resp = client.post(
        "/api/v1/medical/zotero-ingest",
        json={
            "collection_name": "rank-med",
            "pdf_dir": str(pdf_dir),
            "zotero_json_path": str(zotero_json),
            "recursive": True,
        },
    )
    assert resp.status_code == 200

    query = "blood pressure trial 2024 New England Journal of Medicine 10.1000/hyper.2024.10"
    search_resp = client.post(
        "/api/v1/medical/search",
        json={
            "query": query,
            "top_k": 5,
            "sources": "local",
            "collection_name": "rank-med",
        },
    )
    assert search_resp.status_code == 200
    data = search_resp.json()
    assert len(data["results"]) >= 1
    top = data["results"][0]
    assert top["doi"] == "10.1000/hyper.2024.10"
    assert top["year"] == 2024
    assert top["journal"] == "New England Journal of Medicine"


def test_polish_evidence_map_prefers_high_quality_source(monkeypatch):
    async def fake_search(_request):
        return MedicalSearchResponse(
            query="q",
            expanded_query="q",
            results=[
                MedicalSearchResult(
                    source_type="local",
                    source="local",
                    title="generic",
                    snippet="Intervention reduces mortality in critical care patients.",
                    score=0.52,
                    page=2,
                    doi=None,
                    year=2012,
                    journal=None,
                ),
                MedicalSearchResult(
                    source_type="local",
                    source="local",
                    title="high_quality",
                    snippet="Intervention reduces mortality in critical care patients.",
                    score=0.55,
                    page=8,
                    doi="10.1000/high.2024.1",
                    year=2024,
                    journal="The Lancet",
                ),
            ],
        )

    monkeypatch.setattr(medical_service, "medical_search", fake_search)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    payload = MedicalPolishRequest(
        text="This intervention reduces mortality in critical care patients.",
        mode="academic",
        require_evidence=True,
        strict_fact_mode=True,
    )
    result = asyncio.run(medical_service.polish_text(payload))
    assert result.evidence_map
    assert result.evidence_map[0].doi == "10.1000/high.2024.1"


@dataclass
class _FakeVectorStore:
    enabled: bool = True
    healthy_value: bool = True
    search_results: list | None = None
    upsert_should_raise: bool = False
    search_should_raise: bool = False

    def healthy(self) -> bool:
        return self.healthy_value

    def upsert_chunks(self, collection_name, chunks):
        if self.upsert_should_raise:
            raise RuntimeError("qdrant down")
        return len(chunks), []

    def search(self, collection_name, query, top_k):
        if self.search_should_raise:
            raise RuntimeError("qdrant query failed")
        return list(self.search_results or [])[:top_k]


def test_ingest_uses_qdrant_when_available(tmp_path, monkeypatch):
    index_file = tmp_path / "medical_index.json"
    monkeypatch.setenv("MEDICAL_INDEX_PATH", str(index_file))
    monkeypatch.setattr(medical_service, "_get_vector_store", lambda: _FakeVectorStore())

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "paper1.txt").write_text("Hypertension treatment outcomes in adults.", encoding="utf-8")

    resp = client.post(
        "/api/v1/medical/ingest",
        json={"doc_path": str(docs_dir), "collection_name": "med-qdrant", "recursive": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["indexed_docs"] == 1
    assert data["index_backend"] in {"qdrant", "dual_write_partial"}


def test_ingest_fallbacks_to_json_when_qdrant_unavailable(tmp_path, monkeypatch):
    index_file = tmp_path / "medical_index.json"
    monkeypatch.setenv("MEDICAL_INDEX_PATH", str(index_file))
    monkeypatch.setattr(
        medical_service,
        "_get_vector_store",
        lambda: _FakeVectorStore(upsert_should_raise=True),
    )

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "paper1.txt").write_text("Hypertension treatment outcomes in adults.", encoding="utf-8")

    resp = client.post(
        "/api/v1/medical/ingest",
        json={"doc_path": str(docs_dir), "collection_name": "med-fallback", "recursive": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["index_backend"] == "json_fallback"
    assert any(item["file"] == "__qdrant__" for item in data["failed_files"])


def test_search_prefers_qdrant_and_fallbacks(tmp_path, monkeypatch):
    index_file = tmp_path / "medical_index.json"
    monkeypatch.setenv("MEDICAL_INDEX_PATH", str(index_file))

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "local.txt").write_text(
        "Hypertension treatment improves blood pressure control in adults.",
        encoding="utf-8",
    )
    client.post(
        "/api/v1/medical/ingest",
        json={"doc_path": str(docs_dir), "collection_name": "med-search", "recursive": True},
    )

    qdrant_results = [
        MedicalSearchResult(
            source_type="local",
            source="qdrant://chunk",
            title="Qdrant hit",
            snippet="vector retrieved document",
            score=0.9,
            doi="10.1000/qdrant.2026.1",
            year=2026,
            journal="Lancet",
        )
    ]
    monkeypatch.setattr(
        medical_service,
        "_get_vector_store",
        lambda: _FakeVectorStore(search_results=qdrant_results),
    )

    resp_a = client.post(
        "/api/v1/medical/search",
        json={"query": "hypertension trial", "top_k": 5, "sources": "local", "collection_name": "med-search"},
    )
    assert resp_a.status_code == 200
    data_a = resp_a.json()
    assert data_a["results"]
    assert data_a["results"][0]["source"] == "qdrant://chunk"

    monkeypatch.setattr(
        medical_service,
        "_get_vector_store",
        lambda: _FakeVectorStore(search_should_raise=True),
    )
    resp_b = client.post(
        "/api/v1/medical/search",
        json={"query": "hypertension trial", "top_k": 5, "sources": "local", "collection_name": "med-search"},
    )
    assert resp_b.status_code == 200
    data_b = resp_b.json()
    assert data_b["results"]
    assert data_b["results"][0]["source"] != "qdrant://chunk"


def test_polish_evidence_map_with_qdrant_candidates(monkeypatch):
    qdrant_results = [
        MedicalSearchResult(
            source_type="local",
            source="qdrant://source-a",
            title="High quality trial",
            snippet="This intervention reduces mortality in critical care patients.",
            score=0.92,
            doi="10.1000/highq.2025.1",
            year=2025,
            journal="New England Journal of Medicine",
        ),
        MedicalSearchResult(
            source_type="local",
            source="qdrant://source-b",
            title="Lower quality",
            snippet="This intervention reduces mortality in critical care patients.",
            score=0.55,
            doi=None,
            year=2010,
            journal=None,
        ),
    ]
    monkeypatch.setattr(
        medical_service,
        "_get_vector_store",
        lambda: _FakeVectorStore(search_results=qdrant_results),
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    resp = client.post(
        "/api/v1/medical/polish",
        json={
            "text": "This intervention reduces mortality in critical care patients.",
            "mode": "academic",
            "require_evidence": True,
            "strict_fact_mode": True,
            "collection_name": "med-polish",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["evidence_map"]
    assert data["evidence_map"][0]["doi"] == "10.1000/highq.2025.1"
