"""Minimal local web application for Create Junior."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from app.domain.models import DesignManifest
from app.storage.fs import ProjectStore


app = FastAPI(title="Create Junior", version="0.1.0")
store = ProjectStore()
web_root = Path(__file__).resolve().parents[1] / "web"


@app.get("/", response_class=FileResponse)
def index() -> FileResponse:
    return FileResponse(web_root / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "create-junior"}


@app.post("/api/projects", response_model=DesignManifest)
def create_project(manifest: DesignManifest | None = None) -> DesignManifest:
    result = manifest or DesignManifest()
    return store.save(result)


@app.get("/api/projects/{project_id}", response_model=DesignManifest)
def get_project(project_id: UUID) -> DesignManifest:
    try:
        return store.load(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@app.put("/api/projects/{project_id}/manifest", response_model=DesignManifest)
def update_manifest(project_id: UUID, manifest: DesignManifest) -> DesignManifest:
    if manifest.project_id != project_id:
        raise HTTPException(status_code=400, detail="Project id does not match manifest")
    return store.save(manifest)
