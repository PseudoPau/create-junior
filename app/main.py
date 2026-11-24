"""FastAPI entry point for the independent Create Junior workbench."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.workbench.api import router as workbench_router
from app.workbench.exports import router as export_router
from app.workbench.run_api import router as run_router
from app.workbench.model_import import router as model_import_router
from app.workbench.domain_flow import create_domain_router
from app.workbench.review_api import create_review_router
from app.workbench import api as workbench_api

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


@app.get("/editor", response_class=FileResponse)
def editor() -> FileResponse:
    return FileResponse(web_root / "editor.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "create-junior", "product": "furniture-workbench"}


app.include_router(workbench_router)
app.include_router(export_router)
app.include_router(run_router)
app.include_router(model_import_router)
app.include_router(create_domain_router(lambda: workbench_api.workbench_store))
app.include_router(create_review_router(lambda: workbench_api.workbench_store))


@app.on_event("startup")
def load_saved_ai_settings() -> None:
    from app.workbench.ai import load_saved_config
    load_saved_config()
