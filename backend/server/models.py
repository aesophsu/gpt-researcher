from __future__ import annotations

from typing import Any, Dict, Generic, List, TypeVar

from pydantic import BaseModel, ConfigDict, Field


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


class ReportRecord(BaseModel):
    id: str
    question: str | None = None
    answer: str | None = None
    orderedData: list[Any] = Field(default_factory=list)
    chatMessages: list[Dict[str, Any]] = Field(default_factory=list)
    timestamp: int


T = TypeVar("T")


class CoreResultEnvelope(BaseModel, Generic[T]):
    ok: bool = True
    data: T | None = None
    error: str | None = None
