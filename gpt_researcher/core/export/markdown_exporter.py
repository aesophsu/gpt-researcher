from __future__ import annotations

import os
import urllib.parse
import uuid
import re
from pathlib import Path

import aiofiles
import mistune

from .ports import ExportTarget, ReportExporterPort


class MarkdownReportExporter(ReportExporterPort):
    async def to_markdown(self, content: str, target: ExportTarget) -> str:
        file_path = self._build_path(target, ".md")
        await self._write_to_file(file_path, content)
        return urllib.parse.quote(file_path)

    async def to_pdf(self, content: str, target: ExportTarget) -> str:
        file_path = self._build_path(target, ".pdf")
        css_path = self._resolve_css_path()

        processed = self._preprocess_images_for_pdf(content)
        from md2pdf.core import md2pdf

        md2pdf(
            file_path,
            md_content=processed,
            css_file_path=css_path,
            base_url=os.path.abspath("."),
        )
        return urllib.parse.quote(file_path)

    async def to_docx(self, content: str, target: ExportTarget) -> str:
        file_path = self._build_path(target, ".docx")
        from docx import Document
        from htmldocx import HtmlToDocx

        html = mistune.html(content)
        doc = Document()
        HtmlToDocx().add_html_to_document(html, doc)
        doc.save(file_path)
        return urllib.parse.quote(file_path)

    async def _write_to_file(self, filename: str, text: str) -> None:
        if not isinstance(text, str):
            text = str(text)
        text_utf8 = text.encode("utf-8", errors="replace").decode("utf-8")
        os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)
        async with aiofiles.open(filename, "w", encoding="utf-8") as file:
            await file.write(text_utf8)

    def _build_path(self, target: ExportTarget, suffix: str) -> str:
        name = (target.filename or uuid.uuid4().hex)[:80]
        os.makedirs(target.output_dir, exist_ok=True)
        return os.path.join(target.output_dir, f"{name}{suffix}")

    def _preprocess_images_for_pdf(self, text: str) -> str:
        base_path = os.path.abspath(".")

        def replace_image_url(match):
            alt_text = match.group(1)
            url = match.group(2)
            if url.startswith("/outputs/"):
                abs_path = os.path.join(base_path, url.lstrip("/"))
                return f"![{alt_text}]({abs_path})"
            return match.group(0)

        pattern = r"!\[([^\]]*)\]\((/outputs/[^)]+)\)"
        return re.sub(pattern, replace_image_url, text)

    def _resolve_css_path(self) -> str | None:
        root = Path(__file__).resolve().parents[3]
        candidates = [
            root / "backend" / "styles" / "pdf_styles.css",
            root / "multi_agents" / "agents" / "utils" / "pdf_styles.css",
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return None
