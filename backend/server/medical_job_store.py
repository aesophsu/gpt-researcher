from __future__ import annotations

from pathlib import Path

from gpt_researcher.core.storage.adapters import JsonJobStoreAdapter


class MedicalJobStore(JsonJobStoreAdapter):
    def __init__(self, path: Path):
        super().__init__(path)
