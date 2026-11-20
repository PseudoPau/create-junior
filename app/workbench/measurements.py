"""Read-only, version-independent measurements for the five chair fit decisions.

Part local axes follow the existing model contract: X is board width, Y is
thickness and Z is board length. A seat uses local +Z as its front direction;
a back uses local +Z as its upward direction. We do not infer these directions
from a display name. Width/depth are the rectangular seat-board envelope along
its surface axes, not a claim about unobstructed human clearance. Irregular
seat outlines need an explicit usable-surface definition before measuring.

Measurements do not imply that the deterministic compiler can edit a design.
The existing compiler still handles only its recognized horizontal six-board
construction. Tilted seats require a complete Agent candidate and checks.
"""
from __future__ import annotations

from hashlib import sha256
import json
from math import acos, asin, degrees, isfinite

from app.workbench.engine import _rotation, _rotate
from app.workbench.models import Project


DIMENSIONS = (
    ("seat_height_mm", "座高", "mm"),
    ("seat_width_mm", "座宽", "mm"),
    ("seat_depth_mm", "座深", "mm"),
    ("seat_tilt_deg", "座面倾角", "°"),
    ("seat_back_angle_deg", "座背夹角", "°"),
)
DIMENSION_KEYS = tuple(item[0] for item in DIMENSIONS)
_EPS = 1e-6


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _bounded(value):
    return max(-1.0, min(1.0, value))


def _without_timestamps(value):
    if isinstance(value, dict):
        return {key: _without_timestamps(item) for key, item in value.items()
                if key not in {"updated_at", "created_at"}}
    if isinstance(value, list):
        return [_without_timestamps(item) for item in value]
    return value


def _context(project: Project, module_id: str | None):
    data = project.model_dump(mode="json")
    if module_id is not None:
        modules = [item for item in data["modules"] if item["id"] == module_id]
    else:
        modules = [item for item in data["modules"] if item["kind"] == "support"]
    if len(modules) != 1:
        return data, None, None, "需要明确唯一的坐姿 Module，不能混用不同椅子的尺寸。"
    module = modules[0]
    member_ids = set(module["affected_part_ids"])
    seats = [part for part in data["parts"]
             if part["id"] in member_ids and part["kind"] == "seat_board"]
    if len(seats) != 1:
        return data, module, None, "当前 Module 需要关联且仅关联一块明确的座板。"
    seat = seats[0]
    if seat.get("outline_mm"):
        return data, module, None, "异形座板尚未定义可用座面，不能用包围盒代替适己尺寸。"
    matrix = _rotation(seat)
    across = _rotate(matrix, [1.0, 0.0, 0.0])
    normal = _rotate(matrix, [0.0, 1.0, 0.0])
    # Side slope or upside-down seat makes the present two-angle contract ambiguous.
    if abs(across[1]) > _EPS or normal[1] <= _EPS:
        return data, module, None, "当前座面存在侧倾或朝向不明确，需要补充座面基准。"
    top_center = [0.0, seat["size_mm"][1] / 2, 0.0]
    if any(_dot(cut["normal_local"], top_center) > cut["offset_mm"] + _EPS
           for cut in seat.get("plane_cuts", [])):
        return data, module, None, "座面中心已被切除，需要明确实际支撑面的测量基准。"
    return data, module, seat, ""


def _back(data, module, seat):
    matrix = _rotation(seat)
    across = _rotate(matrix, [1.0, 0.0, 0.0])
    front = _rotate(matrix, [0.0, 0.0, 1.0])
    attached = {pid for joint in data["joints"] if seat["id"] in joint["part_ids"]
                for pid in joint["part_ids"] if pid != seat["id"]}
    members = set(module["affected_part_ids"])
    candidates = []
    for part in data["parts"]:
        if part["id"] not in attached & members or part.get("outline_mm"):
            continue
        axes = _rotation(part)
        up = _rotate(axes, [0.0, 0.0, 1.0])
        back_across = _rotate(axes, [1.0, 0.0, 0.0])
        relative = [part["position_mm"][i] - seat["position_mm"][i] for i in range(3)]
        # Only a connected rear board with an upward local Z axis and a shared
        # transverse axis defines the signed chair side plane unambiguously.
        if (up[1] > .5 and abs(abs(_dot(across, back_across)) - 1) < _EPS
                and _dot(relative, front) < -_EPS):
            candidates.append(part)
    return candidates[0] if len(candidates) == 1 else None


def _compiler(data, module):
    if module is None:
        return False
    from app.workbench.module_fit import _layout
    try:
        _layout(data, module)
    except ValueError:
        return False
    return True


def _fingerprint(item, data, module):
    if item["current_value"] is None or module is None:
        return None
    # Geometrically unrelated edits should not re-ask the same fit decision.
    # Measurement value and membership establish this dimension's dependency;
    # profile and use intent establish the user's decision context.
    dependency = {
        "key": item["key"], "value": item["current_value"],
        "unit": item["unit"], "basis": item["measurement_basis"],
        "part_ids": item["part_ids"], "module_id": module["id"],
        "purpose": module.get("purpose"), "posture": module.get("posture"),
        "anthropometry": _without_timestamps(module.get("anthropometry", {})),
        "profile_snapshot": _without_timestamps(data.get("profile_snapshot")),
    }
    return sha256(json.dumps(dependency, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def dimension_items(project: Project, module_id: str | None = None) -> list[dict]:
    """Return all five decisions, preserving unknown measurements explicitly.

    ``capability`` describes editing, not measuring or comfort validation.
    ``legacy_key`` is provided only when the current deterministic compiler is
    applicable. No existing target/decision keys are rewritten by this read.
    """
    data, module, seat, reason = _context(project, module_id)
    items = [{"key": key, "label": label, "unit": unit, "current_value": None,
              "status": "unknown", "reason": reason,
              "module_id": module["id"] if module else module_id,
              "part_ids": [], "measurement_basis": None,
              "capability": "unavailable", "legacy_key": None,
              "fingerprint": None} for key, label, unit in DIMENSIONS]
    if seat is None:
        return items
    matrix = _rotation(seat)
    front = _rotate(matrix, [0.0, 0.0, 1.0])
    top = _rotate(matrix, [0.0, seat["size_mm"][1] / 2, 0.0])
    values = {
        "seat_height_mm": seat["position_mm"][1] + top[1],
        "seat_width_mm": seat["size_mm"][0],
        "seat_depth_mm": seat["size_mm"][2],
        "seat_tilt_deg": degrees(asin(_bounded(front[1]))),
    }
    back = _back(data, module, seat)
    if back is not None:
        up = _rotate(_rotation(back), [0.0, 0.0, 1.0])
        values["seat_back_angle_deg"] = degrees(acos(_bounded(_dot(front, up))))
    local = _compiler(data, module)
    reasons = {
        "seat_height_mm": "地面基准 y=0 到座板上表面中心的垂直距离。",
        "seat_width_mm": "座板沿局部 X 的总宽；尚不等同于扣除侧挡后的净空。",
        "seat_depth_mm": "座板沿局部 Z 的总长；尚不等同于扣除靠背后的净座深。",
        "seat_tilt_deg": "座面前向相对水平面的角度；正值表示前高后低。",
        "seat_back_angle_deg": "座面前向与靠背向上方向的夹角，由当前相对变换测量。",
    }
    for item in items:
        key = item["key"]
        if key not in values:
            item["reason"] = "未找到唯一且方向明确的关联靠背，需要补充坐姿基准。"
            continue
        value = round(values[key], 6)
        item.update(current_value=0.0 if value == 0 else value, status="measured",
                    reason=reasons[key], part_ids=[seat["id"]], capability="agent_required",
                    measurement_basis="seat_board_envelope" if key in {"seat_width_mm", "seat_depth_mm"}
                    else "surface_center_height" if key == "seat_height_mm" else "world_axis_angle")
        if key == "seat_back_angle_deg":
            item["part_ids"].append(back["id"])
        if local and key != "seat_tilt_deg":
            item.update(capability="local_compiler",
                        legacy_key="back_angle_deg" if key == "seat_back_angle_deg" else key)
        item["fingerprint"] = _fingerprint(item, data, module)
    return items


def measurement_fingerprint(project: Project, module_id: str | None, key: str) -> str | None:
    """Unknown measurements cannot produce a confirmable dependency signature."""
    if key not in DIMENSION_KEYS:
        raise ValueError("未知的适己尺寸")
    return next(item["fingerprint"] for item in dimension_items(project, module_id) if item["key"] == key)


def legacy_edit(project: Project, module_id: str, key: str, value: float) -> tuple[str, float]:
    """Translate only a currently supported edit into the legacy compiler API.

    A tilted seat never silently treats ``included angle - 90`` as back tilt.
    Ranges and constructibility are still checked by fit_preview itself.
    """
    if key not in DIMENSION_KEYS or not isfinite(value):
        raise ValueError("需要有效的适己尺寸")
    item = next(item for item in dimension_items(project, module_id) if item["key"] == key)
    if item["capability"] != "local_compiler":
        raise ValueError("这项尺寸需要 Agent 返回包含板件、孔位和连接的关联修改。")
    return item["legacy_key"], value - 90 if key == "seat_back_angle_deg" else value
