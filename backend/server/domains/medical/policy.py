from __future__ import annotations

from datetime import datetime


def evidence_quality_adjustment(score: float, doi: str | None, journal: str | None, year: int | None, source: str) -> float:
    adjusted = score
    if doi:
        adjusted += 0.12
    if journal:
        adjusted += 0.08
    if isinstance(year, int):
        age = max(0, datetime.now().year - year)
        if age <= 2:
            adjusted += 0.08
        elif age <= 5:
            adjusted += 0.04
    if source == "pubmed_central":
        adjusted += 0.06
    elif source == "semantic_scholar":
        adjusted += 0.04
    return min(1.0, max(0.0, adjusted))
