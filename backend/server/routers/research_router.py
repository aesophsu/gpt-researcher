from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, File, UploadFile
from fastapi.responses import FileResponse

from ..dependencies import get_dependencies
from ..models import ResearchRequest

router = APIRouter(tags=["research"])


@router.get("/report/{research_id}")
async def read_report(research_id: str):
    docx_path = await get_dependencies().research_service.get_generated_docx(research_id)
    if not docx_path:
        return {"message": "Report not found."}
    return FileResponse(docx_path)


@router.post("/report/")
async def generate_report(research_request: ResearchRequest, background_tasks: BackgroundTasks):
    return await get_dependencies().research_service.generate_report(research_request, background_tasks)


@router.get("/files/")
async def list_files():
    files = await get_dependencies().research_service.list_files()
    return {"files": files}


@router.post("/upload/")
async def upload_file(file: UploadFile = File(...)):
    return await get_dependencies().research_service.upload_file(file)


@router.delete("/files/{filename}")
async def delete_file(filename: str):
    return await get_dependencies().research_service.delete_file(filename)


@router.post("/api/multi_agents")
async def run_multi_agents():
    return await get_dependencies().research_service.run_multi_agents()
