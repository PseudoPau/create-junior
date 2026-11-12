"""Domain models for the first Create Junior workflow."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ReferenceSource(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    kind: Literal["url", "image"]
    uri: str
    title: str | None = None
    description: str | None = None
    media_type: str | None = None
    asset_path: str | None = None


class Evidence(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    source_id: str | None = None
    statement: str
    confidence: Literal["confirmed", "estimated", "unknown"] = "estimated"
    note: str | None = None


class UserProfile(BaseModel):
    seat_height_mm: float | None = Field(default=None, gt=0)
    seat_width_mm: float | None = Field(default=None, gt=0)
    seat_depth_mm: float | None = Field(default=None, gt=0)
    user_height_mm: float | None = Field(default=None, gt=0)
    estimated_load_kg: float | None = Field(default=None, gt=0)


class MaterialSpec(BaseModel):
    kind: Literal["solid_wood", "panel", "unknown"] = "unknown"
    name: str | None = None
    stock_width_mm: float | None = Field(default=None, gt=0)
    stock_thickness_mm: float | None = Field(default=None, gt=0)
    available_length_mm: float | None = Field(default=None, gt=0)
    grain_direction: Literal["part_length", "part_width", "unknown"] = "unknown"
    properties: dict[str, float | str | None] = Field(default_factory=dict)


class PartSpec(BaseModel):
    id: str
    name: str
    kind: Literal["side_panel", "seat_board", "brace", "unknown"]
    quantity: int = Field(default=1, ge=1)
    dimensions_mm: dict[str, float] = Field(default_factory=dict)
    material_ref: str | None = None
    grain_direction: Literal["length", "width", "unknown"] = "unknown"
    evidence_ids: list[str] = Field(default_factory=list)


class JoinerySpec(BaseModel):
    id: str
    kind: Literal["half_lap", "dowel", "screw", "unknown"]
    part_ids: list[str] = Field(min_length=2)
    dimensions_mm: dict[str, float] = Field(default_factory=dict)
    tool_notes: list[str] = Field(default_factory=list)
    status: Literal["candidate", "confirmed"] = "candidate"


class ValidationIssue(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    severity: Literal["pass", "warning", "unknown"]
    code: str
    message: str
    related_ids: list[str] = Field(default_factory=list)


class DesignManifest(BaseModel):
    project_id: UUID = Field(default_factory=uuid4)
    name: str = "Untitled stool"
    version: int = Field(default=1, ge=1)
    reference_sources: list[ReferenceSource] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    user_profile: UserProfile = Field(default_factory=UserProfile)
    materials: dict[str, MaterialSpec] = Field(default_factory=dict)
    parts: list[PartSpec] = Field(default_factory=list)
    joinery: list[JoinerySpec] = Field(default_factory=list)
    validation: list[ValidationIssue] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
