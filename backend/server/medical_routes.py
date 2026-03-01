from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .models import CoreResultEnvelope
from .medical_models import (
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
from .medical_service import (
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


@router.post("/ingest")
async def medical_ingest(payload: MedicalIngestRequest) -> CoreResultEnvelope[MedicalIngestResponse]:
    return CoreResultEnvelope(data=await ingest_documents(payload))


@router.post("/zotero-ingest")
async def medical_zotero_ingest(payload: ZoteroIngestRequest) -> CoreResultEnvelope[ZoteroIngestResponse]:
    return CoreResultEnvelope(data=await ingest_zotero_documents(payload))


@router.post("/ingest/async")
async def medical_ingest_async(payload: MedicalIngestRequest) -> CoreResultEnvelope[MedicalJobCreateResponse]:
    return CoreResultEnvelope(data=await start_medical_ingest_job(payload))


@router.post("/zotero-ingest/async")
async def medical_zotero_ingest_async(payload: ZoteroIngestRequest) -> CoreResultEnvelope[MedicalJobCreateResponse]:
    return CoreResultEnvelope(data=await start_zotero_ingest_job(payload))


@router.get("/jobs/{job_id}")
async def medical_job_status(job_id: str) -> CoreResultEnvelope[MedicalJobStatusResponse]:
    job = await get_medical_job_status(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Medical job not found: {job_id}")
    return CoreResultEnvelope(data=job)


@router.post("/search")
async def medical_search_endpoint(payload: MedicalSearchRequest) -> CoreResultEnvelope[MedicalSearchResponse]:
    return CoreResultEnvelope(data=await medical_search(payload))


@router.post("/polish")
async def medical_polish(payload: MedicalPolishRequest) -> CoreResultEnvelope[MedicalPolishResponse]:
    return CoreResultEnvelope(data=await polish_text(payload))


@router.post("/citation-audit")
async def medical_citation_audit(payload: CitationAuditRequest) -> CoreResultEnvelope[CitationAuditResponse]:
    return CoreResultEnvelope(data=await citation_audit(payload))
