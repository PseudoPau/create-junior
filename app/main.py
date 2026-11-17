"""FastAPI entry point for the independent Create Junior workbench."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.workbench.api import router as workbench_router

app = FastAPI(
    title="Create Junior",
    version="0.2.0",
    description="A local-first furniture recreation and DIY customization workbench.",
)
web_root = Path(__file__).resolve().parents[1] / "web"
app.mount("/static", StaticFiles(directory=web_root), name="static")


@app.get("/", response_class=FileResponse)
def index() -> FileResponse:
    return FileResponse(web_root / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "create-junior", "product": "furniture-workbench"}


app.include_router(workbench_router)
