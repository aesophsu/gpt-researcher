from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any


class MedicalJobStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._state = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"jobs": {}}
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "jobs" in data:
                return data
        except Exception:
            pass
        return {"jobs": {}}

    def _save(self) -> None:
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(self._state, f, ensure_ascii=True, indent=2)

    async def create_job(self, job_id: str, job_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            now = int(time.time() * 1000)
            job = {
                "job_id": job_id,
                "job_type": job_type,
                "status": "pending",
                "created_at": now,
                "updated_at": now,
                "payload": payload,
                "progress": {
                    "stage": "pending",
                    "message": "queued",
                    "total_files": 0,
                    "processed_files": 0,
                    "skipped_files": 0,
                    "indexed_docs": 0,
                    "chunks": 0,
                    "failed_files": 0,
                },
                "result": None,
                "error": None,
            }
            self._state["jobs"][job_id] = job
            self._save()
            return job

    async def set_running(self, job_id: str) -> None:
        async with self._lock:
            job = self._state["jobs"].get(job_id)
            if not job:
                return
            job["status"] = "running"
            job["updated_at"] = int(time.time() * 1000)
            self._save()

    async def update_progress(self, job_id: str, **progress_patch: Any) -> None:
        async with self._lock:
            job = self._state["jobs"].get(job_id)
            if not job:
                return
            progress = job.get("progress") or {}
            progress.update(progress_patch)
            job["progress"] = progress
            job["updated_at"] = int(time.time() * 1000)
            self._save()

    async def set_completed(self, job_id: str, result: dict[str, Any]) -> None:
        async with self._lock:
            job = self._state["jobs"].get(job_id)
            if not job:
                return
            job["status"] = "completed"
            job["result"] = result
            job["error"] = None
            job["updated_at"] = int(time.time() * 1000)
            self._save()

    async def set_failed(self, job_id: str, error: str) -> None:
        async with self._lock:
            job = self._state["jobs"].get(job_id)
            if not job:
                return
            job["status"] = "failed"
            job["error"] = error
            job["updated_at"] = int(time.time() * 1000)
            self._save()

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        async with self._lock:
            return self._state["jobs"].get(job_id)
