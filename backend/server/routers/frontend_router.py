from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from ..dependencies import get_dependencies

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def serve_frontend():
    frontend_dir = get_dependencies().frontend_dir
    index_path = os.path.join(frontend_dir, "index.html")

    if not os.path.exists(index_path):
        raise HTTPException(status_code=404, detail="Frontend index.html not found")

    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()

    return HTMLResponse(content=content)
