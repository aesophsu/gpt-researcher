from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class MedicalIngestRequest(BaseModel):
    doc_path: str
    collection_name: str = "default"
    recursive: bool = True


class FailedFile(BaseModel):
    file: str
    reason: str


class MedicalIngestResponse(BaseModel):
    indexed_docs: int
    chunks: int
    skipped_files: int = 0
    failed_files: List[FailedFile] = Field(default_factory=list)
    index_backend: Optional[Literal["qdrant", "json_fallback", "dual_write_partial"]] = None
    index_warnings: List[str] = Field(default_factory=list)


class ZoteroIngestRequest(BaseModel):
    collection_name: str = "default"
    pdf_dir: str
    zotero_json_path: Optional[str] = None
    bibtex_path: Optional[str] = None
    recursive: bool = True


class ZoteroMatchStats(BaseModel):
    pdf_files: int = 0
    matched_metadata: int = 0
    unmatched_pdf_files: int = 0
    json_entries: int = 0
    bib_entries: int = 0


class ZoteroIngestResponse(MedicalIngestResponse):
    collection_name: str
    match_stats: ZoteroMatchStats


class MedicalJobCreateResponse(BaseModel):
    job_id: str
    status: Literal["pending", "running", "completed", "failed"]


class MedicalJobProgress(BaseModel):
    stage: str = "pending"
    message: str = ""
    total_files: int = 0
    processed_files: int = 0
    skipped_files: int = 0
    indexed_docs: int = 0
    chunks: int = 0
    failed_files: int = 0


class MedicalJobStatusResponse(BaseModel):
    job_id: str
    job_type: str
    status: Literal["pending", "running", "completed", "failed"]
    created_at: int
    updated_at: int
    progress: MedicalJobProgress
    result: Optional[dict] = None
    error: Optional[str] = None


class MedicalSearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=8, ge=1, le=50)
    sources: Literal["local", "web", "hybrid"] = "hybrid"
    collection_name: str = "default"


class MedicalSearchResult(BaseModel):
    source_type: Literal["local", "web"]
    source: str
    title: Optional[str] = None
    snippet: str
    score: float = 0.0
    page: Optional[int] = None
    doi: Optional[str] = None
    year: Optional[int] = None
    journal: Optional[str] = None
    url: Optional[str] = None


class MedicalSearchResponse(BaseModel):
    query: str
    expanded_query: str
    results: List[MedicalSearchResult] = Field(default_factory=list)


class MedicalPolishRequest(BaseModel):
    text: str
    mode: Literal["concise", "academic", "journal"] = "academic"
    journal_style: Optional[str] = None
    require_evidence: bool = True
    section_type: Optional[Literal["introduction", "methods", "results", "discussion", "other"]] = None
    strict_fact_mode: bool = True
    target_journal: Optional[str] = None
    collection_name: str = "default"


class RevisionItem(BaseModel):
    sentence_id: str
    original: str
    revised: str
    reason: str


class EvidenceRef(BaseModel):
    sentence_id: str
    source: str
    page: Optional[int] = None
    snippet: str
    confidence: float = 0.0
    doi: Optional[str] = None


class MedicalPolishResponse(BaseModel):
    revisions: List[RevisionItem]
    evidence_map: List[EvidenceRef] = Field(default_factory=list)
    risk_flags: List[str] = Field(default_factory=list)


class CitationAuditRequest(BaseModel):
    manuscript_text: str
    format: Literal["auto", "apa", "vancouver"] = "auto"
    references: Optional[List[str]] = None


class CitationIssue(BaseModel):
    sentence_id: str
    sentence: str
    reason: str


class CitationAuditResponse(BaseModel):
    missing_citations: List[CitationIssue] = Field(default_factory=list)
    weak_claims: List[CitationIssue] = Field(default_factory=list)
    unmatched_citations: List[CitationIssue] = Field(default_factory=list)
    unused_references: List[str] = Field(default_factory=list)
    format_issues: List[str] = Field(default_factory=list)
    consistency_score: float = 0.0
