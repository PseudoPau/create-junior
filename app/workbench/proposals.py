"""Shared proposal boundary for local imports and remote model suggestions."""
from copy import deepcopy
from uuid import uuid4
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.workbench.models import Project, EDITABLE_FIELDS
from app.workbench.engine import build_package
from app.workbench.revisions import invalidate_connections


class ImportProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=1)
    summary: str = Field(min_length=1, max_length=8000)
    patch: dict
    purpose: Literal["design", "manufacturing"] = "design"


def proposal_schema() -> dict:
    schema = Project.model_json_schema()
    return {
        "type": "object", "additionalProperties": False,
        "required": ["summary", "patch"], "$defs": schema.get("$defs", {}),
        "properties": {
            "summary": {"type": "string", "maxLength": 8000},
            "patch": {"type": "object", "additionalProperties": False,
                      "description": "Omitted fields remain unchanged. Included objects and arrays replace the entire field; return their complete new value.",
                      "properties": {key: val for key, val in schema["properties"].items()
                                     if key in EDITABLE_FIELDS}},
        },
    }


def build_proposal(project: Project, summary: str, patch: dict, purpose: str = "design") -> dict:
    if purpose not in {"design", "manufacturing"}:
        raise ValueError("无效候选用途")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 8000:
        raise ValueError("候选说明必须为 1 到 8000 字符")
    if not isinstance(patch, dict) or set(patch) - EDITABLE_FIELDS:
        raise ValueError("候选只能修改设计字段，不能修改项目身份、参考文件或确认状态")
    # Validate shape before inspecting nested values, then clear confirmation flags.
    candidate = Project.model_validate({**project.model_dump(mode="json"), **deepcopy(patch)})
    if "scale" in patch and candidate.scale:
        candidate.scale.confirmed = False
    if "joints" in patch:
        for joint in candidate.joints:
            joint.confirmed = False
    known_sources = {ref.id for ref in project.references}
    if any(set(e.source_ids) - known_sources for e in candidate.evidence):
        raise ValueError("候选证据引用了当前项目不存在的参考图片")
    candidate.confirmed_revision = None
    candidate.acknowledged_limits = False
    normalized = candidate.model_dump(mode="json")
    normalized_patch = {key: normalized[key] for key in patch}
    # The committed write and candidate preview obey one invalidation rule.
    invalidate_connections(project, normalized)
    package = build_package(normalized)
    return {"id": str(uuid4()), "base_revision": project.revision, "status": "ready",
            "summary": summary, "patch": normalized_patch, "purpose": purpose,
            "package_preview": package,
            "checks": package["checks"], "coverage": package.get("coverage", {})}
