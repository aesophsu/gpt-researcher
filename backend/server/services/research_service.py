from __future__ import annotations

import os
import time
from typing import Dict

from fastapi import BackgroundTasks

from gpt_researcher.utils.enum import Tone
from ...utils import write_md_to_pdf, write_md_to_word

from ..server_utils import (
    execute_multi_agents,
    handle_file_deletion,
    handle_file_upload,
    sanitize_filename,
)
from ..websocket_manager import run_agent, WebSocketManager
from ..models import ResearchRequest


class ResearchService:
    def __init__(self, manager: WebSocketManager, doc_path: str):
        self.manager = manager
        self.doc_path = doc_path

    async def write_report(self, research_request: ResearchRequest, research_id: str | None = None):
        report_information = await run_agent(
            task=research_request.task,
            report_type=research_request.report_type,
            report_source=research_request.report_source,
            source_urls=[],
            document_urls=[],
            tone=Tone[research_request.tone],
            websocket=None,
            stream_output=None,
            headers=research_request.headers,
            query_domains=[],
            config_path="",
            return_researcher=True,
        )

        docx_path = await write_md_to_word(report_information[0], research_id)
        pdf_path = await write_md_to_pdf(report_information[0], research_id)

        if research_request.report_type != "multi_agents":
            report, researcher = report_information
            return {
                "research_id": research_id,
                "research_information": {
                    "source_urls": researcher.get_source_urls(),
                    "research_costs": researcher.get_costs(),
                    "visited_urls": list(researcher.visited_urls),
                    "research_images": researcher.get_research_images(),
                },
                "report": report,
                "docx_path": docx_path,
                "pdf_path": pdf_path,
            }

        return {"research_id": research_id, "report": "", "docx_path": docx_path, "pdf_path": pdf_path}

    async def generate_report(self, research_request: ResearchRequest, background_tasks: BackgroundTasks):
        research_id = sanitize_filename(f"task_{int(time.time())}_{research_request.task}")

        if research_request.generate_in_background:
            background_tasks.add_task(self.write_report, research_request=research_request, research_id=research_id)
            return {
                "message": "Your report is being generated in the background. Please check back later.",
                "research_id": research_id,
            }
        return await self.write_report(research_request, research_id)

    async def get_generated_docx(self, research_id: str) -> str | None:
        docx_path = os.path.join("outputs", f"{research_id}.docx")
        return docx_path if os.path.exists(docx_path) else None

    async def list_files(self) -> list[str]:
        if not os.path.exists(self.doc_path):
            os.makedirs(self.doc_path, exist_ok=True)
        return os.listdir(self.doc_path)

    async def upload_file(self, file):
        return await handle_file_upload(file, self.doc_path)

    async def delete_file(self, filename: str):
        return await handle_file_deletion(filename, self.doc_path)

    async def run_multi_agents(self):
        return await execute_multi_agents(self.manager)
