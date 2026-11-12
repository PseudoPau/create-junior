"""Small, explainable woodworking checks for the first stool workflow."""

from __future__ import annotations

from app.domain.models import DesignManifest, ValidationIssue


def validate_manifest(manifest: DesignManifest) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    profile = manifest.user_profile
    required_profile = {
        "seat_height_mm": profile.seat_height_mm,
        "seat_width_mm": profile.seat_width_mm,
        "seat_depth_mm": profile.seat_depth_mm,
    }
    for name, value in required_profile.items():
        if value is None:
            issues.append(ValidationIssue(severity="unknown", code="missing_dimension", message=f"缺少 {name}。"))
        elif value <= 0:
            issues.append(ValidationIssue(severity="warning", code="invalid_dimension", message=f"{name} 必须大于 0。"))

    material = manifest.materials.get("main")
    if material is None:
        issues.append(ValidationIssue(severity="unknown", code="missing_material", message="尚未选择主要材料。"))
    elif material.stock_thickness_mm is None:
        issues.append(ValidationIssue(severity="unknown", code="missing_stock_thickness", message="主要材料缺少板厚或料厚。"))
    elif material.stock_thickness_mm <= 0:
        issues.append(ValidationIssue(severity="warning", code="invalid_stock_thickness", message="材料厚度必须大于 0。"))

    part_ids = {part.id for part in manifest.parts}
    for part in manifest.parts:
        if any(value <= 0 for value in part.dimensions_mm.values()):
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="invalid_part_dimension",
                    message=f"部件 {part.name} 包含非正尺寸。",
                    related_ids=[part.id],
                )
            )
    for joint in manifest.joinery:
        missing_parts = [part_id for part_id in joint.part_ids if part_id not in part_ids]
        if missing_parts:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="joinery_part_missing",
                    message=f"接合 {joint.id} 引用了不存在的部件。",
                    related_ids=[joint.id, *missing_parts],
                )
            )
        if joint.status != "confirmed":
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="joinery_unconfirmed",
                    message=f"接合 {joint.id} 仍是候选方案，需要用户确认。",
                    related_ids=[joint.id],
                )
            )

    if not issues:
        issues.append(ValidationIssue(severity="pass", code="basic_checks_passed", message="基础尺寸、材料和接合引用检查通过。"))
    return issues
