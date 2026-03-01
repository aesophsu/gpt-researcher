from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict


class ResearchRequest(BaseModel):
    task: str
    report_type: str
    report_source: str
    tone: str
    headers: dict | None = None
    repo_name: str
    branch_name: str
    generate_in_background: bool = True


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    report: str
    messages: List[Dict[str, Any]]
