"""Small conservative material library and preliminary seat-load estimate."""

from __future__ import annotations

from math import ceil
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.models import DesignManifest, MaterialSpec, ValidationIssue


class MaterialPreset(BaseModel):
    name: str
    kind: Literal["solid_wood", "panel"]
    density_kg_m3: float = Field(gt=0)
    elastic_modulus_mpa: float = Field(gt=0)
    bending_strength_mpa: float = Field(gt=0)
    connection_allowable_n: float = Field(gt=0)
    source: str
    conservative: bool = True


class LoadEstimate(BaseModel):
    status: Literal["pass", "warning", "unknown"]
    requested_load_kg: float | None = None
    material_name: str | None = None
    material_source: str | None = None
    bending_stress_mpa: float | None = None
    allowable_stress_mpa: float | None = None
    deflection_mm: float | None = None
    assumptions: list[str] = Field(default_factory=list)
    issues: list[ValidationIssue] = Field(default_factory=list)


MATERIAL_PRESETS: dict[str, MaterialPreset] = {
    "pine": MaterialPreset(name="松木（保守估计）", kind="solid_wood", density_kg_m3=500, elastic_modulus_mpa=8000, bending_strength_mpa=40, connection_allowable_n=300, source="Create Junior conservative preset"),
    "beech": MaterialPreset(name="山毛榉（保守估计）", kind="solid_wood", density_kg_m3=700, elastic_modulus_mpa=11000, bending_strength_mpa=80, connection_allowable_n=600, source="Create Junior conservative preset"),
    "oak": MaterialPreset(name="橡木（保守估计）", kind="solid_wood", density_kg_m3=700, elastic_modulus_mpa=10000, bending_strength_mpa=70, connection_allowable_n=500, source="Create Junior conservative preset"),
    "plywood": MaterialPreset(name="胶合板（保守估计）", kind="panel", density_kg_m3=600, elastic_modulus_mpa=7000, bending_strength_mpa=35, connection_allowable_n=250, source="Create Junior conservative preset"),
}


def resolve_material(material: MaterialSpec) -> MaterialPreset | None:
    key = (material.name or "").strip().lower()
    preset = MATERIAL_PRESETS.get(key)
    if preset is None:
        return None
    overrides = material.properties
    return preset.model_copy(update={
        "density_kg_m3": float(overrides.get("density_kg_m3", preset.density_kg_m3)),
        "elastic_modulus_mpa": float(overrides.get("elastic_modulus_mpa", preset.elastic_modulus_mpa)),
        "bending_strength_mpa": float(overrides.get("bending_strength_mpa", preset.bending_strength_mpa)),
        "connection_allowable_n": float(overrides.get("connection_allowable_n", preset.connection_allowable_n)),
        "source": "user override" if overrides else preset.source,
    })


def estimate_seat_load(manifest: DesignManifest, safety_factor: float = 3.0) -> LoadEstimate:
    material = manifest.materials.get("main")
    load_kg = manifest.user_profile.estimated_load_kg
    width = manifest.user_profile.seat_width_mm
    depth = manifest.user_profile.seat_depth_mm
    thickness = material.stock_thickness_mm if material else None
    if material is None or load_kg is None or width is None or depth is None or thickness is None:
        return LoadEstimate(
            status="unknown",
            requested_load_kg=load_kg,
            assumptions=["需要材料、座面尺寸和预估载荷；缺少信息时不做承载结论。"],
            issues=[ValidationIssue(severity="unknown", code="load_inputs_missing", message="承载估算缺少材料、座面尺寸或预估载荷。")],
        )
    preset = resolve_material(material)
    if preset is None:
        return LoadEstimate(
            status="unknown",
            requested_load_kg=load_kg,
            assumptions=["当前材料不在内置保守材料库中，需用户提供参数。"],
            issues=[ValidationIssue(severity="unknown", code="material_properties_missing", message="无法找到该材料的弹性模量和抗弯强度。")],
        )
    support_width = 50.0
    span = max(width - 2 * support_width, width * 0.5)
    load_n = load_kg * 9.81
    section_modulus = depth * thickness**2 / 6
    inertia = depth * thickness**3 / 12
    bending_stress = load_n * span / 4 / section_modulus
    allowable = preset.bending_strength_mpa / safety_factor
    deflection = load_n * span**3 / (48 * preset.elastic_modulus_mpa * inertia)
    stress_ok = bending_stress <= allowable
    deflection_ok = deflection <= span / 240
    status: Literal["pass", "warning"] = "pass" if stress_ok and deflection_ok else "warning"
    issues = []
    if not stress_ok:
        issues.append(ValidationIssue(severity="warning", code="seat_bending_high", message="简化座面抗弯应力超过保守允许值。"))
    if not deflection_ok:
        issues.append(ValidationIssue(severity="warning", code="seat_deflection_high", message="简化座面挠度超过 span/240 提示阈值。"))
    return LoadEstimate(
        status=status,
        requested_load_kg=load_kg,
        material_name=preset.name,
        material_source=preset.source,
        bending_stress_mpa=round(bending_stress, 3),
        allowable_stress_mpa=round(allowable, 3),
        deflection_mm=round(deflection, 3),
        assumptions=[
            "按座面两侧简支、中央集中载荷、矩形截面估算。",
            f"支持宽度按 {support_width:g} mm 估算，安全系数为 {safety_factor:g}。",
            "未考虑木纹、缺陷、湿度、长期蠕变、接合滑移和侧向稳定性。",
            "结果仅用于早期方案筛查，不是工程安全认证。",
        ],
        issues=issues,
    )
