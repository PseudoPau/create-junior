"""Reference analysis contracts independent of any AI provider."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class CandidateDimension(BaseModel):
    name: str
    value_mm: float | None = Field(default=None, gt=0)
    confidence: Literal["confirmed", "estimated", "unknown"] = "unknown"
    evidence_ids: list[str] = Field(default_factory=list)


class PartCandidate(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    name: str
    kind: Literal["side_panel", "seat_board", "brace", "unknown"] = "unknown"
    observations: list[str] = Field(default_factory=list)
    dimensions: list[CandidateDimension] = Field(default_factory=list)


class JoineryCandidate(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    kind: Literal["half_lap", "dowel", "screw", "unknown"] = "unknown"
    part_names: list[str] = Field(default_factory=list)
    rationale: str = ""
    confidence: Literal["confirmed", "estimated", "unknown"] = "unknown"


class ReferenceAnalysis(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    source_ids: list[str] = Field(default_factory=list)
    provider: str = "draft"
    status: Literal["draft", "ready", "failed"] = "draft"
    summary: str = "尚未完成参考分析。"
    style_notes: list[str] = Field(default_factory=list)
    parts: list[PartCandidate] = Field(default_factory=list)
    joinery: list[JoineryCandidate] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
