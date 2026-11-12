"""Minimal local web application for Create Junior."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse

from app.analysis.models import ReferenceAnalysis
from app.analysis.provider import configured_analyzer
from app.domain.models import DesignManifest, ReferenceSource
from app.domain.validation import validate_manifest
from app.fabrication.package import FabricationPackage, build_fabrication_package
from app.materials.library import LoadEstimate, estimate_seat_load
from app.storage.fs import ProjectStore


app = FastAPI(title="Create Junior", version="0.1.0")
store = ProjectStore()
analyzer = configured_analyzer(store.root)
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


@app.post("/api/projects/{project_id}/references", response_model=DesignManifest)
def add_reference(project_id: UUID, source: ReferenceSource) -> DesignManifest:
    try:
        manifest = store.load(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    manifest.reference_sources.append(source)
    manifest.version += 1
    return store.save(manifest)


@app.post("/api/projects/{project_id}/reference-file", response_model=DesignManifest)
async def upload_reference_file(
    project_id: UUID,
    request: Request,
    filename: str = Query(default="reference-image"),
) -> DesignManifest:
    try:
        manifest = store.load(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    content = await request.body()
    if not content:
        raise HTTPException(status_code=400, detail="Reference file is empty")
    asset_path = store.save_reference(project_id, filename, content)
    manifest.reference_sources.append(
        ReferenceSource(
            kind="image",
            uri=asset_path,
            asset_path=asset_path,
            media_type=request.headers.get("content-type"),
        )
    )
    manifest.version += 1
    return store.save(manifest)


@app.get("/api/projects/{project_id}/fabrication-package", response_model=FabricationPackage)
def get_fabrication_package(project_id: UUID) -> FabricationPackage:
    try:
        manifest = store.load(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    return build_fabrication_package(manifest)


@app.get("/api/projects/{project_id}/load-estimate", response_model=LoadEstimate)
def get_load_estimate(project_id: UUID) -> LoadEstimate:
    try:
        manifest = store.load(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    return estimate_seat_load(manifest)
@app.post("/api/projects/{project_id}/validate", response_model=DesignManifest)
def validate_project(project_id: UUID) -> DesignManifest:
    try:
        manifest = store.load(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    manifest.validation = validate_manifest(manifest)
    manifest.version += 1
    return store.save(manifest)
@app.post("/api/projects/{project_id}/analyze", response_model=ReferenceAnalysis)
async def analyze_references(project_id: UUID) -> ReferenceAnalysis:
    try:
        manifest = store.load(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    analysis = await analyzer.analyze(manifest)
    return store.save_analysis(analysis)


@app.get("/api/projects/{project_id}/analysis", response_model=ReferenceAnalysis)
def get_analysis(project_id: UUID) -> ReferenceAnalysis:
    try:
        return store.load_analysis(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Analysis not found") from exc






