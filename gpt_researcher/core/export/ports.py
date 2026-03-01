from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ExportTarget:
    output_dir: str = "outputs"
    filename: str = ""


class ReportExporterPort(Protocol):
    async def to_markdown(self, content: str, target: ExportTarget) -> str:
        ...

    async def to_pdf(self, content: str, target: ExportTarget) -> str:
        ...

    async def to_docx(self, content: str, target: ExportTarget) -> str:
        ...
