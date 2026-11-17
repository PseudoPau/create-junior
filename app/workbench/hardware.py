"""Resolve physical hardware from machining-feature anchors.

Anchors are persisted in part-local feature space. World positions are derived
for both the viewport and drawings; changes to a part move its hardware with it.
A bolt origin is its under-head bearing plane. Other origins are the near end.
"""
from __future__ import annotations
from collections import Counter
from math import sqrt
from pydantic import ValidationError
from app.workbench.models import Hardware


def _data(value):
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def feature_axis(part, feature):
    # Share the engine's single XYZ/face convention; importing at call time lets
    # build_checks use this module without a module-initialization cycle.
    from app.workbench.engine import _hole_segment
    return _hole_segment(part, feature)


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _length(v):
    return sqrt(_dot(v, v))


def _resolve(project):
    project = _data(project)
    parts = {part["id"]: part for part in project.get("parts", [])}
    features = {(part["id"], feature["id"]): feature
                for part in parts.values() for feature in part.get("features", [])}
    counts = Counter(instance.get("id") for joint in project.get("joints", [])
                     for item in joint.get("hardware", []) for instance in item.get("instances", []))
    resolved, checks = [], []
    def issue(code, message, part_ids, severity="blocker"):
        checks.append({"code": code, "severity": severity, "message": message, "part_ids": list(part_ids)})
    for joint in project.get("joints", []):
        joint_ids = joint.get("part_ids", [])
        for index, raw in enumerate(joint.get("hardware", [])):
            label = (joint.get("name") or joint["id"]) + " / " + raw.get("name", str(index + 1))
            try:
                hardware = Hardware.model_validate(raw).model_dump(mode="json")
            except ValidationError:
                issue("hardware_geometry_invalid", label + "：几何规格无效。", joint_ids)
                continue
            geometry, instances = hardware.get("geometry"), hardware.get("instances", [])
            if not geometry:
                if instances:
                    issue("hardware_geometry_missing", label + "：安装实例没有几何规格。", joint_ids)
                else:
                    issue("hardware_geometry_unavailable", label + "：仅有采购记录，未定义五金实体。", joint_ids, "info")
                continue
            if len(instances) != hardware["quantity"]:
                issue("hardware_instance_count", label + "：实体数量与采购数量不一致。", joint_ids)
                continue
            for instance in instances:
                iid, pid, fid = instance["id"], instance["part_id"], instance["feature_id"]
                feature, part = features.get((pid, fid)), parts.get(pid)
                if counts[iid] != 1:
                    issue("hardware_instance_duplicate", label + "：五金实例编号重复 " + iid, joint_ids)
                    continue
                if (part is None or feature is None or feature.get("kind") != "hole"
                        or pid not in joint_ids or fid not in joint.get("feature_ids", [])):
                    issue("hardware_anchor_invalid", label + "：安装锚点不属于本连接的有效孔。", joint_ids)
                    continue
                # Invalid holes are already domain blockers; do not draw hardware
                # against an impossible entry point or direction.
                from app.workbench.engine import _feature_error
                if _feature_error(part, feature):
                    issue("hardware_anchor_invalid", label + "：安装锚点的孔位或深度无效。", [pid])
                    continue
                entry, direction, _ = feature_axis(part, feature)
                position = [entry[i] + direction[i] * instance["offset_mm"] for i in range(3)]
                item = {"id": iid, "joint_id": joint["id"], "name": hardware["name"],
                        "spec": hardware["spec"], "kind": geometry["kind"], "geometry": geometry,
                        "position_mm": position, "direction": direction,
                        "part_id": pid, "feature_id": fid}
                if geometry["kind"] == "barrel_nut":
                    bid, bfid = instance.get("bore_part_id"), instance.get("bore_feature_id")
                    bpart, bfeature = parts.get(bid), features.get((bid, bfid))
                    if (bpart is None or bfeature is None or bid not in joint_ids
                            or bfid not in joint.get("feature_ids", [])
                            or bfeature.get("kind") != "hole" or _feature_error(bpart, bfeature)):
                        issue("hardware_cross_bore_anchor", label + "：横孔螺母需要明确的主螺纹孔轴。", joint_ids)
                        continue
                    bore_entry, bore_direction, bore_depth = feature_axis(bpart, bfeature)
                    center = [position[i] + direction[i] * geometry["length_mm"] / 2 for i in range(3)]
                    delta = [center[i] - bore_entry[i] for i in range(3)]
                    t = _dot(delta, bore_direction)
                    radial = [delta[i] - t * bore_direction[i] for i in range(3)]
                    if abs(_dot(direction, bore_direction)) > .01 or _length(radial) > .5 or not -.5 <= t <= bore_depth + .5:
                        issue("hardware_cross_bore_misaligned", label + "：横孔螺母中心未对准主孔钻孔段。", joint_ids)
                        continue
                    item["bore_direction"] = bore_direction
                resolved.append(item)
    return resolved, checks


def resolve_hardware(project) -> list[dict]:
    """Return valid placed solids. Never invent placements from spec text."""
    return _resolve(project)[0]


def hardware_checks(project) -> list[dict]:
    """Validate references, quantities and explicit cross-bore alignment."""
    return _resolve(project)[1]
