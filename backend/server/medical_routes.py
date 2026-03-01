from __future__ import annotations

from fastapi import APIRouter, HTTPException

from server.medical_models import (
    CitationAuditRequest,
    CitationAuditResponse,
    MedicalJobCreateResponse,
    MedicalJobStatusResponse,
    MedicalIngestRequest,
    MedicalIngestResponse,
    MedicalPolishRequest,
    MedicalPolishResponse,
    MedicalSearchRequest,
    MedicalSearchResponse,
    ZoteroIngestRequest,
    ZoteroIngestResponse,
)
from server.medical_service import (
    citation_audit,
    get_medical_job_status,
    ingest_documents,
    ingest_zotero_documents,
    medical_search,
    polish_text,
    start_medical_ingest_job,
    start_zotero_ingest_job,
)

router = APIRouter(prefix="/api/v1/medical", tags=["medical"])


@router.post("/ingest", response_model=MedicalIngestResponse)
async def medical_ingest(payload: MedicalIngestRequest) -> MedicalIngestResponse:
    return await ingest_documents(payload)


@router.post("/zotero-ingest", response_model=ZoteroIngestResponse)
async def medical_zotero_ingest(payload: ZoteroIngestRequest) -> ZoteroIngestResponse:
    return await ingest_zotero_documents(payload)


@router.post("/ingest/async", response_model=MedicalJobCreateResponse)
async def medical_ingest_async(payload: MedicalIngestRequest) -> MedicalJobCreateResponse:
    return await start_medical_ingest_job(payload)


@router.post("/zotero-ingest/async", response_model=MedicalJobCreateResponse)
async def medical_zotero_ingest_async(payload: ZoteroIngestRequest) -> MedicalJobCreateResponse:
    return await start_zotero_ingest_job(payload)


@router.get("/jobs/{job_id}", response_model=MedicalJobStatusResponse)
async def medical_job_status(job_id: str) -> MedicalJobStatusResponse:
    job = await get_medical_job_status(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Medical job not found: {job_id}")
    return job


@router.post("/search", response_model=MedicalSearchResponse)
async def medical_search_endpoint(payload: MedicalSearchRequest) -> MedicalSearchResponse:
    return await medical_search(payload)


@router.post("/polish", response_model=MedicalPolishResponse)
async def medical_polish(payload: MedicalPolishRequest) -> MedicalPolishResponse:
    return await polish_text(payload)


@router.post("/citation-audit", response_model=CitationAuditResponse)
async def medical_citation_audit(payload: CitationAuditRequest) -> CitationAuditResponse:
    return await citation_audit(payload)
