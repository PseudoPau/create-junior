"""Pair a joint's existing holes by moving the counterpart hole onto the source axis.

This is a geometric suggestion, not a structural approval: the caller still
previews, applies, and reruns every check.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.workbench.engine import (
    FACE_AXES, _feature_error, _hole_segment, _holes_match, _rotation, _dot,
)


def _holes(part: dict) -> list[dict]:
    return [feature for feature in part.get("features", [])
            if feature.get("kind") == "hole" and feature.get("role", "connection") == "connection"
            and not _feature_error(part, feature)]


def _target_position(source: dict, source_feature: dict, target: dict, target_feature: dict, equal_diameter: bool):
    """Return (u, v) for target_feature, or None when the faces cannot pair."""
    entry, direction, _ = _hole_segment(source, source_feature)
    axes = FACE_AXES.get(target_feature.get("face"))
    if not axes:
        return None
    axis_u, axis_v, axis_n = axes
    size = target["size_mm"]
    positive = target_feature["face"] in ("top", "right", "front")
    local_normal = [0.0, 0.0, 0.0]
    local_normal[axis_n] = -1.0 if positive else 1.0
    matrix = _rotation(target)
    normal = [sum(matrix[i][j] * local_normal[j] for j in range(3)) for i in range(3)]
    if abs(_dot(direction, normal)) < 0.999999:
        return None
    face_center = [0.0, 0.0, 0.0]
    face_center[axis_n] = size[axis_n] / 2 * (1 if positive else -1)
    center_world = [target["position_mm"][i] + sum(matrix[i][j] * face_center[j] for j in range(3)) for i in range(3)]
    denom = _dot(direction, normal)
    if abs(denom) < 1e-9:
        return None
    t = _dot([center_world[i] - entry[i] for i in range(3)], normal) / denom
    hit = [entry[i] + t * direction[i] for i in range(3)]
    delta = [hit[i] - target["position_mm"][i] for i in range(3)]
    inverse = [[matrix[j][i] for j in range(3)] for i in range(3)]
    local = [sum(inverse[i][j] * delta[j] for j in range(3)) for i in range(3)]
    u = local[axis_u] + size[axis_u] / 2
    v = local[axis_v] + size[axis_v] / 2
    candidate = deepcopy(target_feature)
    candidate["u_mm"], candidate["v_mm"] = round(u, 3), round(v, 3)
    if _feature_error(target, candidate):
        return None
    if not _holes_match(source, source_feature, target, candidate, equal_diameter):
        return None
    return candidate["u_mm"], candidate["v_mm"]


def pair_joint_preview(project: Any, joint_id: str) -> dict:
    data = project.model_dump(mode="json") if hasattr(project, "model_dump") else deepcopy(project)
    joint = next((item for item in data.get("joints", []) if item.get("id") == joint_id), None)
    if joint is None:
        raise ValueError("找不到这个连接。")
    if joint.get("kind") not in ("screw", "dowel"):
        raise ValueError("只有螺钉或木销连接可按同轴孔配对；偏心件/半搭接请先定孔槽。")
    parts = {part["id"]: part for part in data.get("parts", [])}
    part_ids = [pid for pid in joint.get("part_ids", []) if pid in parts]
    if len(part_ids) < 2:
        raise ValueError("连接缺少两个已有零件。")
    equal_diameter = joint.get("kind") == "dowel"
    for source_id in part_ids:
        source = parts[source_id]
        for source_feature in _holes(source):
            if source_feature["id"] not in joint.get("feature_ids", []):
                continue
            if any(other != source_id and _holes_match(source, source_feature, parts[other], candidate, equal_diameter)
                   for other in part_ids for candidate in _holes(parts[other])):
                continue
            for target_id in part_ids:
                if target_id == source_id:
                    continue
                target = parts[target_id]
                for target_feature in _holes(target):
                    if target_feature["id"] not in joint.get("feature_ids", []):
                        continue
                    result = _target_position(source, source_feature, target, target_feature, equal_diameter)
                    if result is None:
                        continue
                    u, v = result
                    patch_parts = deepcopy(data["parts"])
                    patched = next(part for part in patch_parts if part["id"] == target_id)
                    feature = next(item for item in patched["features"] if item["id"] == target_feature["id"])
                    feature["u_mm"], feature["v_mm"] = u, v
                    source_name = source.get("name", source_id)
                    target_name = target.get("name", target_id)
                    return {
                        "summary": f"{joint.get('name', joint_id)}：把 {target_name} 的孔 {target_feature['id']} 移到与 {source_name} 的孔 {source_feature['id']} 同轴。",
                        "patch": {"parts": patch_parts},
                        "pairs": [{"source": source_feature["id"], "target": target_feature["id"], "u_mm": u, "v_mm": v}],
                    }
    raise ValueError("这个连接没有可在现有孔/面之间自动配对的组合；请改孔面或手动调整。")
