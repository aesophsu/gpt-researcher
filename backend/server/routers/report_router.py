from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..dependencies import get_dependencies
from ..models import CoreResultEnvelope

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("")
async def get_all_reports(report_ids: str = None):
    reports = await get_dependencies().report_service.list_reports(report_ids)
    return CoreResultEnvelope(data={"reports": reports})


@router.get("/{research_id}")
async def get_report_by_id(research_id: str):
    report = await get_dependencies().report_service.get_report_or_none(research_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return CoreResultEnvelope(data={"report": report})


@router.post("")
async def create_or_update_report(request: Request):
    data = await request.json()
    research_id = await get_dependencies().report_service.create_or_update_report(data)
    return CoreResultEnvelope(data={"id": research_id})


@router.put("/{research_id}")
async def update_report(research_id: str, request: Request):
    data = await request.json()
    updated = await get_dependencies().report_service.update_report(research_id, data)
    if not updated:
        raise HTTPException(status_code=404, detail="Report not found")
    return CoreResultEnvelope(data={"id": research_id})


@router.delete("/{research_id}")
async def delete_report(research_id: str):
    existed = await get_dependencies().report_service.delete_report(research_id)
    if not existed:
        raise HTTPException(status_code=404, detail="Report not found")
    return CoreResultEnvelope(data={"deleted": True})


@router.get("/{research_id}/chat")
async def get_report_chat(research_id: str):
    chat_messages = await get_dependencies().report_service.get_chat_messages(research_id)
    if chat_messages is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return CoreResultEnvelope(data={"chatMessages": chat_messages})


@router.post("/{research_id}/chat")
async def add_report_chat_message(research_id: str, request: Request):
    message = await request.json()
    updated = await get_dependencies().report_service.add_chat_message(research_id, message)
    if not updated:
        raise HTTPException(status_code=404, detail="Report not found")
    return CoreResultEnvelope(data={"id": research_id})
