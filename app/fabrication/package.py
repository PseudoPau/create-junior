"""Manufacturing package contracts and deterministic first-pass generation."""

from __future__ import annotations

from html import escape
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.airport.stool import DesignIncomplete, derive_stool_parts
from app.domain.models import DesignManifest, PartSpec, ValidationIssue
from app.domain.validation import validate_manifest


class CutListItem(BaseModel):
    part_id: str
    name: str
    quantity: int
    material: str | None = None
    dimensions_mm: dict[str, float] = Field(default_factory=dict)
    grain_direction: str = "unknown"


class PartDrawing(BaseModel):
    part_id: str
    filename: str
    svg: str
    status: Literal["ready", "incomplete"]
    missing: list[str] = Field(default_factory=list)


class AssemblyStep(BaseModel):
    order: int
    title: str
    instruction: str
    part_ids: list[str] = Field(default_factory=list)
    tool_notes: list[str] = Field(default_factory=list)


class FabricationPackage(BaseModel):
    project_id: UUID
    manifest_version: int
    status: Literal["ready", "incomplete"]
    cut_list: list[CutListItem] = Field(default_factory=list)
    drawings: list[PartDrawing] = Field(default_factory=list)
    joinery_notes: list[str] = Field(default_factory=list)
    assembly_steps: list[AssemblyStep] = Field(default_factory=list)
    validation: list[ValidationIssue] = Field(default_factory=list)


def _drawing_svg(part: PartSpec) -> str:
    width = part.dimensions_mm.get("width", 100)
    height = part.dimensions_mm.get("height", part.dimensions_mm.get("depth", 100))
    scale = min(420 / max(width, 1), 260 / max(height, 1))
    rect_width = max(width * scale, 1)
    rect_height = max(height * scale, 1)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="520" height="340" viewBox="0 0 520 340">'
        f'<rect x="40" y="30" width="{rect_width:.2f}" height="{rect_height:.2f}" fill="#ead5bd" stroke="#24231f" stroke-width="2"/>'
        f'<text x="40" y="320" font-family="sans-serif" font-size="16">{escape(part.name)} · {width:g} × {height:g} mm</text>'
        '</svg>'
    )


def build_fabrication_package(manifest: DesignManifest) -> FabricationPackage:
    validation = validate_manifest(manifest)
    try:
        parts = manifest.parts or derive_stool_parts(manifest)
    except DesignIncomplete as exc:
        parts = []
        validation.append(ValidationIssue(severity="unknown", code="parts_not_derived", message=str(exc)))
    drawings: list[PartDrawing] = []
    cut_list: list[CutListItem] = []
    status: Literal["ready", "incomplete"] = "ready" if parts else "incomplete"
    for part in parts:
        missing = [name for name in ("width", "height") if name not in part.dimensions_mm]
        if missing:
            status = "incomplete"
        drawings.append(
            PartDrawing(
                part_id=part.id,
                filename=f"{part.id}.svg",
                svg=_drawing_svg(part) if not missing else "",
                status="ready" if not missing else "incomplete",
                missing=missing,
            )
        )
        cut_list.append(
            CutListItem(
                part_id=part.id,
                name=part.name,
                quantity=part.quantity,
                material=part.material_ref,
                dimensions_mm=part.dimensions_mm,
                grain_direction=part.grain_direction,
            )
        )

    joinery_notes = [
        f"{joint.id}: {joint.kind}，连接 {', '.join(joint.part_ids)}，状态 {joint.status}。"
        for joint in manifest.joinery
    ]
    if not manifest.joinery:
        joinery_notes.append("接合方式尚未确认，当前加工包不能作为最终施工依据。")
        status = "incomplete"
    assembly_steps = [
        AssemblyStep(order=1, title="核对部件", instruction="按部件编号核对数量、尺寸和木纹方向。", part_ids=[part.id for part in parts]),
        AssemblyStep(order=2, title="试装接合", instruction="不涂胶先试装所有接合，确认方向和间隙。", part_ids=[part.id for part in parts]),
        AssemblyStep(order=3, title="完成固定", instruction="按已确认的接合说明完成固定，并检查椅面水平。", part_ids=[part.id for part in parts]),
    ]
    return FabricationPackage(
        project_id=manifest.project_id,
        manifest_version=manifest.version,
        status=status,
        cut_list=cut_list,
        drawings=drawings,
        joinery_notes=joinery_notes,
        assembly_steps=assembly_steps,
        validation=validation,
    )


