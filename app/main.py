"""Minimal local web application for Create Junior."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.analysis.models import ReferenceAnalysis
from app.airport.client import AirportToolError, AirportUnavailable, McpAirportClient
from app.airport.orchestrator import commit_stool
from app.airport.stool import DesignIncomplete, derive_stool_proposal
from app.analysis.provider import configured_analyzer
from app.domain.models import DesignManifest, ReferenceSource
from app.domain.validation import validate_manifest
from app.fabrication.package import FabricationPackage, build_fabrication_package
from app.fabrication.export import build_fabrication_archive
from app.materials.library import LoadEstimate, estimate_seat_load
from app.storage.fs import ProjectStore


app = FastAPI(title="Create Junior", version="0.1.0")
store = ProjectStore()
analyzer = configured_analyzer(store.root)
web_root = Path(__file__).resolve().parents[1] / "web"
app.mount('/static', StaticFiles(directory=web_root), name='static')


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
    try:
        previous = store.load(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    if manifest.project_id != project_id:
        raise HTTPException(status_code=400, detail="Project id does not match manifest")
    design_inputs_changed = (
        manifest.user_profile != previous.user_profile
        or manifest.materials != previous.materials
        or manifest.reference_sources != previous.reference_sources
    )
    if design_inputs_changed:
        manifest.parts = []
        manifest.joinery = []
        manifest.validation = []
    manifest.version = max(manifest.version, previous.version) + 1
    manifest.updated_at = datetime.now(timezone.utc)
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


@app.get("/api/airport/status")
async def airport_status() -> dict:
    client = McpAirportClient()
    if not client.is_reachable():
        return {"status": "unavailable", "url": client.url, "message": "Airport MCP endpoint is not listening", "local_outputs_available": True}
    try:
        return {"status": "ready", "url": client.url, "details": await client.status()}
    except (AirportUnavailable, AirportToolError) as exc:
        return {"status": "unavailable", "url": client.url, "message": str(exc)}


@app.post("/api/projects/{project_id}/airport/commit")
async def commit_project_to_airport(project_id: UUID) -> dict:
    try:
        manifest = store.load(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    issues = validate_manifest(manifest)
    blocking = [issue for issue in issues if issue.severity == "unknown"]
    if blocking:
        raise HTTPException(status_code=409, detail={"message": "Design needs confirmation before Airport commit", "issues": [issue.model_dump() for issue in blocking]})
    try:
        result = await commit_stool(McpAirportClient(), manifest)
    except AirportUnavailable as exc:
        raise HTTPException(status_code=503, detail={"code": "AIRPORT_UNAVAILABLE", "message": str(exc), "local_outputs_available": True}) from exc
    except AirportToolError as exc:
        raise HTTPException(status_code=502, detail={"code": "AIRPORT_TOOL_ERROR", "message": str(exc), "local_outputs_available": True}) from exc
    return {"status": "committed", "project_id": str(project_id), "result": result}
@app.get("/api/projects/{project_id}/fabrication-package", response_model=FabricationPackage)
def get_fabrication_package(project_id: UUID) -> FabricationPackage:
    try:
        manifest = store.load(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    return build_fabrication_package(manifest)


@app.get("/api/projects/{project_id}/fabrication-package/download")
def download_fabrication_package(project_id: UUID) -> Response:
    try:
        manifest = store.load(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    _, archive = build_fabrication_archive(manifest)
    return Response(
        content=archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="create-junior-{project_id}.zip"'},
    )


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


@app.post("/api/projects/{project_id}/proposal", response_model=DesignManifest)
def generate_structure_proposal(project_id: UUID) -> DesignManifest:
    try:
        manifest = store.load(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    try:
        parts, joinery = derive_stool_proposal(manifest)
    except DesignIncomplete as exc:
        raise HTTPException(status_code=409, detail={"code": "DESIGN_INCOMPLETE", "message": str(exc)}) from exc
    manifest.parts = parts
    manifest.joinery = joinery
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










