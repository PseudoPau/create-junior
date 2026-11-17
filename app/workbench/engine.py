"""Deterministic document checks and drawings from the workbench's single design.

All lengths are millimetres. Parts use centre positions and XYZ rotations.
Face coordinates always follow the positive local axes, never a mirrored
viewer convention: top/bottom=(x,z), front/back=(x,y), left/right=(z,y).
Document readiness is not a structural-safety result.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from html import escape
from math import cos, hypot, isfinite, radians, sin
from typing import Any
from app.workbench.hardware import hardware_checks, resolve_hardware
from app.workbench.solid import cuts_error, drill_error, solid_vertices

FACE_AXES = {
    "top": (0, 2, 1), "bottom": (0, 2, 1),
    "front": (0, 1, 2), "back": (0, 1, 2),
    "left": (2, 1, 0), "right": (2, 1, 0),
}
FACE_LABELS = {
    "top": "顶面 X/Z", "bottom": "底面 X/Z",
    "front": "前面 X/Y", "back": "背面 X/Y",
    "left": "左面 Z/Y", "right": "右面 Z/Y",
}
EPS = 1e-6


def _data(value: Any) -> dict:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def _number(value: Any, positive: bool = False) -> bool:
    return (
        isinstance(value, (float, int))
        and not isinstance(value, bool)
        and isfinite(value)
        and (not positive or value > 0)
    )


def _vector(value: Any, positive: bool = False) -> bool:
    return isinstance(value, (list, tuple)) and len(value) == 3 and all(_number(v, positive) for v in value)


def _cross(a: list, b: list, p: list) -> float:
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def _on_segment(a: list, b: list, p: list) -> bool:
    return (
        abs(_cross(a, b, p)) <= EPS
        and min(a[0], b[0]) - EPS <= p[0] <= max(a[0], b[0]) + EPS
        and min(a[1], b[1]) - EPS <= p[1] <= max(a[1], b[1]) + EPS
    )


def _segments_intersect(a: list, b: list, c: list, d: list) -> bool:
    products = (_cross(a, b, c) * _cross(a, b, d), _cross(c, d, a) * _cross(c, d, b))
    return (
        (products[0] < -EPS and products[1] < -EPS)
        or _on_segment(a, b, c) or _on_segment(a, b, d)
        or _on_segment(c, d, a) or _on_segment(c, d, b)
    )


def _inside(point: list, polygon: list) -> bool:
    result = False
    for i, a in enumerate(polygon):
        b = polygon[(i + 1) % len(polygon)]
        if _on_segment(a, b, point):
            return True
        if (a[1] > point[1]) != (b[1] > point[1]):
            x = (b[0] - a[0]) * (point[1] - a[1]) / (b[1] - a[1]) + a[0]
            if point[0] < x:
                result = not result
    return result


def _outline_error(part: dict) -> str | None:
    polygon, size = part.get("outline_mm"), part.get("size_mm")
    if polygon is None:
        return None
    if not isinstance(polygon, list) or len(polygon) < 3:
        return "斜切轮廓至少需要三个顶点。"
    if not all(isinstance(p, (list, tuple)) and len(p) == 2 and all(_number(v) for v in p) for p in polygon):
        return "轮廓坐标必须是有限的 X/Z 数值。"
    if any(not (0 <= p[0] <= size[0] and 0 <= p[1] <= size[2]) for p in polygon):
        return "轮廓超出零件毛坯的 X/Z 尺寸。"
    area = sum(p[0] * polygon[(i + 1) % len(polygon)][1] - polygon[(i + 1) % len(polygon)][0] * p[1] for i, p in enumerate(polygon))
    if abs(area) < EPS:
        return "轮廓面积为零。"
    n = len(polygon)
    for i in range(n):
        a, b = polygon[i], polygon[(i + 1) % n]
        if a == b:
            return "轮廓有重复相邻顶点。"
        for j in range(i + 1, n):
            if j == (i + 1) % n or (j + 1) % n == i:
                continue
            if _segments_intersect(a, b, polygon[j], polygon[(j + 1) % n]):
                return "轮廓自相交。"
    return None


def _feature_extent(feature: dict) -> tuple[float, float] | None:
    if feature.get("kind") == "hole":
        diameter = feature.get("diameter_mm")
        return (diameter, diameter) if _number(diameter, True) else None
    if feature.get("kind") == "slot":
        width, length = feature.get("width_mm"), feature.get("length_mm")
        return (width, length) if _number(width, True) and _number(length, True) else None
    return None


def _feature_error(part: dict, feature: dict) -> str | None:
    cut_error=cuts_error(part)
    if cut_error:return cut_error
    if feature.get("role", "connection") not in {"connection", "hardware_access"}:
        return "孔槽用途必须是连接孔或五金安装孔。"
    axes = FACE_AXES.get(feature.get("face"))
    extent = _feature_extent(feature)
    if not axes or not extent:
        return "孔槽需要有效加工面、种类和尺寸。"
    u, v, depth = feature.get("u_mm"), feature.get("v_mm"), feature.get("depth_mm")
    if not _number(u) or not _number(v) or not _number(depth, True):
        return "孔槽需要有效定位坐标和加工深度。"
    size = part["size_mm"]
    explicit=feature.get("entry_mm") is not None or feature.get("direction_local") is not None
    if explicit:
        entry,direction=feature.get("entry_mm"),feature.get("direction_local")
        if feature["kind"]!="hole" or not _vector(entry) or not _vector(direction) or abs(_dot(direction,direction)-1)>EPS:
            return "斜孔需要明确入口、单位轴向和孔径。"
        if part.get("outline_mm"):return "显式斜孔暂不与顶面轮廓组合。"
        if abs(u-(entry[axes[0]]+size[axes[0]]/2))>.001 or abs(v-(entry[axes[1]]+size[axes[1]]/2))>.001:
            return "孔 U/V 与显式入口坐标不一致。"
        return drill_error(part,entry,direction,depth,extent[0]/2)
    # Hole U/V is its centre; slot U/V is its rectangle minimum corner.
    left = u - extent[0] / 2 if feature["kind"] == "hole" else u
    bottom = v - extent[1] / 2 if feature["kind"] == "hole" else v
    if left < -EPS or bottom < -EPS or left + extent[0] > size[axes[0]] + EPS or bottom + extent[1] > size[axes[1]] + EPS:
        return "孔槽超出加工面；孔 U/V 是圆心，槽 U/V 是矩形最小角。"
    if depth > size[axes[2]] + EPS:
        return "孔槽深度超过该面的零件厚度。"
    if part.get("plane_cuts"):
        if feature["kind"]!="hole":return "斜切板件目前只支持明确孔加工。"
        entry,direction=_local_hole_axis(part,feature)
        error=drill_error(part,entry,direction,depth,extent[0]/2)
        if error:return error
    outline = part.get("outline_mm")
    if outline:
        if feature["face"] not in ("top", "bottom"):
            return "斜切轮廓的侧面孔槽尚不能验证，请改为顶/底加工或补充加工方案。"
        corners = [[left, bottom], [left + extent[0], bottom], [left + extent[0], bottom + extent[1]], [left, bottom + extent[1]]]
        if not all(_inside(c, outline) for c in corners):
            return "孔槽包围区域不在斜切后的零件轮廓内。"
        # Nonconvex outlines may cross the footprint even when every corner is inside.
        for i, a in enumerate(corners):
            b = corners[(i + 1) % 4]
            for j, c in enumerate(outline):
                d = outline[(j + 1) % len(outline)]
                if _cross(a, b, c) * _cross(a, b, d) < -EPS and _cross(c, d, a) * _cross(c, d, b) < -EPS:
                    return "孔槽包围区域跨越了零件轮廓边缘。"
    return None


def _rotation(part: dict) -> list[list[float]]:
    rx, ry, rz = map(radians, part.get("rotation_deg", [0, 0, 0]))
    cx, cy, cz, sx, sy, sz = cos(rx), cos(ry), cos(rz), sin(rx), sin(ry), sin(rz)
    # Three.js Euler XYZ matrix; R = Rx Ry Rz.
    return [
        [cy * cz, -cy * sz, sy],
        [cx * sz + sx * sy * cz, cx * cz - sx * sy * sz, -sx * cy],
        [sx * sz - cx * sy * cz, sx * cz + cx * sy * sz, cx * cy],
    ]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _rotate(matrix: list[list[float]], vector: list[float]) -> list[float]:
    return [_dot(row, vector) for row in matrix]


def _bounds(part: dict) -> tuple[list[float], list[float]]:
    matrix = _rotation(part)
    if part.get("plane_cuts"):
        points=[_rotate(matrix,p) for p in solid_vertices(part)]
        center=part.get("position_mm",[0,0,0])
        return ([min(p[i] for p in points)+center[i] for i in range(3)],
                [max(p[i] for p in points)+center[i] for i in range(3)])
    half = [v / 2 for v in part["size_mm"]]
    radius = [sum(abs(matrix[i][j]) * half[j] for j in range(3)) for i in range(3)]
    center = part.get("position_mm", [0, 0, 0])
    return ([center[i] - radius[i] for i in range(3)], [center[i] + radius[i] for i in range(3)])


def _local_hole_axis(part: dict, feature: dict):
    if feature.get("entry_mm") is not None:
        return list(feature["entry_mm"]),list(feature["direction_local"])
    size,face=part["size_mm"],feature["face"]
    a,b,normal=FACE_AXES[face];positive=face in ("top","right","front")
    local=[-v/2 for v in size];local[a]+=feature["u_mm"];local[b]+=feature["v_mm"]
    local[normal]=size[normal]/2*(1 if positive else -1)
    inward=[0.,0.,0.];inward[normal]=-1. if positive else 1.
    return local,inward


def _hole_segment(part: dict, feature: dict) -> tuple[list[float], list[float], float]:
    """World entry point, inward unit direction and drilled length."""
    local,inward=_local_hole_axis(part,feature);matrix=_rotation(part)
    point=[v+part["position_mm"][i] for i,v in enumerate(_rotate(matrix,local))]
    return point,_rotate(matrix,inward),feature["depth_mm"]


def _holes_match(part_a: dict, feature_a: dict, part_b: dict, feature_b: dict, equal_diameter: bool) -> bool:
    a, direction, length = _hole_segment(part_a, feature_a)
    b, other_direction, other_length = _hole_segment(part_b, feature_b)
    alignment = _dot(direction, other_direction)
    if abs(alignment) < 0.999999:
        return False
    delta = [b[i] - a[i] for i in range(3)]
    if not all(_number(value) for value in (*a, *b, *direction, *other_direction, *delta)):
        return False
    along = _dot(delta, direction)
    if not _number(along):
        return False
    lateral = hypot(*(delta[i] - along * direction[i] for i in range(3)))
    if not _number(lateral) or lateral > 0.5:
        return False
    start, end = sorted((along, along + alignment * other_length))
    if max(0.0, start) > min(length, end) + 0.5:
        return False
    if equal_diameter and abs(feature_a["diameter_mm"] - feature_b["diameter_mm"]) > 0.01:
        return False
    return True


def build_checks(project: Any) -> list[dict]:
    """Validate manufacturing information, not whole-chair structural safety."""
    project = _data(project)
    checks: list[dict] = []

    def add(code: str, message: str, ids: list[str] | None = None, severity: str = "blocker") -> None:
        checks.append({"code": code, "severity": severity, "message": message, "part_ids": ids or []})

    references = project.get("references", [])
    if not any(r.get("id") for r in references):
        add("reference_views_missing", "请添加参考图片、链接、图纸或说明。")
    if project.get("scope") != "supported":
        add("scope_unconfirmed", project.get("scope_reason") or "需要确认参考属于平直板材/木条木椅范围。")
    scale = project.get("scale") or {}
    if not scale.get("confirmed") or scale.get("kind") not in ("target", "reference") or not str(scale.get("note") or "").strip():
        add("scale_unconfirmed", "请确认原物尺度或本次改制的目标尺度。")
    if project.get("fabrication_mode") not in ("self", "shop"):
        add("fabrication_mode_missing", "请确认自行加工或加工店制件后装配。")
    requirements = project.get("requirements") or {}
    if not _number(requirements.get("load_kg"), True):
        add("load_missing", "请填写使用者预计载荷，用于记录使用条件；这不构成承重认证。")
    parts = project.get("parts", [])
    if not parts:
        add("parts_missing", "尚无已采用的零件设计。")
    part_map, feature_map = {}, {}
    valid_geometry: set[str] = set()
    materials = project.get("materials") or {}
    for part in parts:
        part_id = part.get("id", "")
        if not part_id or part_id in part_map:
            add("part_id_invalid", "零件编号必须非空且唯一。", [part_id])
        part_map[part_id] = part
        if not _vector(part.get("size_mm"), True) or not _vector(part.get("position_mm")) or not _vector(part.get("rotation_deg")):
            add("part_geometry_invalid", "零件需要完整的正尺寸、位置和旋转数值。", [part_id])
            continue
        error = _outline_error(part) or cuts_error(part)
        if error:
            add("outline_invalid", error, [part_id])
        else:
            valid_geometry.add(part_id)
        material = materials.get(part.get("material_id"))
        if not material or not material.get("name") or material.get("kind") not in ("solid_wood", "panel"):
            add("material_missing", "零件缺少已选择的实木/板材。", [part_id])
        elif material.get("grain_axis") not in ("x", "z"):
            add("grain_unconfirmed", "请确认零件局部 X 或 Z 方向的木纹/板材主方向。", [part_id])
        for feature in part.get("features", []):
            fid = feature.get("id", "")
            if not fid or fid in feature_map:
                add("feature_id_invalid", "加工特征编号必须非空且在项目内唯一。", [part_id])
            feature_map[fid] = (part_id, feature)
            if not error:
                feature_error = _feature_error(part, feature)
                if feature_error:
                    add("feature_invalid", f"{fid}：{feature_error}", [part_id])

    # Modules are the user-intent layer. They are checked when present, while
    # older projects without modules remain valid and keep the existing checks.
    modules = project.get("modules") or []
    module_ids: set[str] = set()
    reference_ids = {ref.get("id") for ref in references}
    for module in modules:
        module_id = module.get("id", "")
        affected = module.get("affected_part_ids") or []
        if not module_id or module_id in module_ids:
            add("module_id_invalid", "使用模块编号必须非空且唯一。", affected)
        module_ids.add(module_id)
        missing_sources = set(module.get("source_ids") or []) - reference_ids
        if missing_sources:
            add("module_source_missing", f"{module_id}：使用模块引用了不存在的参考依据。", affected)
        missing_parts = [part_id for part_id in affected if part_id not in part_map]
        if missing_parts:
            add("module_parts_missing", f"{module_id}：关联部件不存在：" + "、".join(missing_parts), missing_parts)
        target = module.get("target") or {}
        status = module.get("status", "inferred")
        for constraint in module.get("constraints") or []:
            key = constraint.get("key", "")
            actual = target.get(key)
            priority = constraint.get("priority", "required")
            severity = "blocker" if priority == "required" and status in {"target", "confirmed", "conflict"} else "warning"
            if not _number(actual, True):
                add("module_constraint_missing", f"{module_id}：缺少“{constraint.get('label') or key}”的目标值。", affected, severity)
                continue
            operator = constraint.get("operator")
            value = constraint.get("value_mm")
            minimum = constraint.get("min_mm")
            maximum = constraint.get("max_mm")
            valid = (
                operator == "gte" and _number(value, True) and actual >= value
                or operator == "lte" and _number(value, True) and actual <= value
                or operator == "eq" and _number(value, True) and abs(actual - value) <= 0.01
                or operator == "range" and _number(minimum, True) and _number(maximum, True) and minimum <= actual <= maximum
            )
            if not valid:
                label = constraint.get("label") or key
                if operator == "range":
                    expectation = f"{minimum}–{maximum}"
                else:
                    expectation = f"{operator} {value}"
                add("module_constraint_violation", f"{module_id}：{label}为 {actual}，不满足 {expectation}。", affected, severity)

    adjacency: dict[str, set[str]] = defaultdict(set)
    used_features: set[str] = set()
    joint_ids: set[str] = set()
    joints = project.get("joints", [])
    if len(parts) > 1 and not joints:
        add("joints_missing", "多零件设计需要明确的连接和装配信息。")
    for joint in joints:
        jid, ids, kind = joint.get("id", ""), joint.get("part_ids", []), joint.get("kind")
        if not jid or jid in joint_ids:
            add("joint_id_invalid", "连接编号必须非空且唯一。", ids)
        joint_ids.add(jid)
        valid_ids = len(ids) >= 2 and len(ids) == len(set(ids)) and all(pid in part_map for pid in ids)
        if not valid_ids:
            add("joint_parts_invalid", f"{jid}：连接必须引用至少两个不同的已有零件。", ids)
        else:
            for pid in ids:
                adjacency[pid].update(set(ids) - {pid})
        if not joint.get("confirmed"):
            add("joint_unconfirmed", f"{jid}：连接做法尚未接受。", ids)
        if not str(joint.get("assembly_note") or "").strip():
            add("assembly_note_missing", f"{jid}：请补充连接的加工与装配做法。", ids)
        if kind not in ("screw", "half_lap", "dowel", "mortise_tenon"):
            add("joint_kind_missing", f"{jid}：连接类型未指定。", ids)
        if kind == "half_lap":
            add("lap_fit_unverified", f"{jid}：当前尚未验证半搭接槽的实体配合，保留草稿但不可作为可加工版本发布。", ids)
        if kind == "mortise_tenon":
            add("tenon_geometry_missing", f"{jid}：当前孔槽数据尚不能完整表达榫头及配合尺寸，不可作为可加工版本发布。", ids)
        feature_ids = joint.get("feature_ids", [])
        owned = set()
        if not feature_ids:
            add("joint_features_missing", f"{jid}：连接只有名称，没有具体孔槽。", ids)
        for fid in feature_ids:
            if fid not in feature_map:
                add("joint_feature_missing", f"{jid}：加工特征 {fid} 不存在。", ids)
                continue
            pid, feature = feature_map[fid]
            if pid not in ids:
                add("joint_feature_owner", f"{jid}：加工特征 {fid} 不属于所连接零件。", ids)
            owned.add(pid)
            used_features.add(fid)
        if feature_ids and set(ids) - owned:
            add("joint_features_incomplete", f"{jid}：每个连接零件都需要明确的加工特征。", ids)
        required_kind = "slot" if kind == "half_lap" else "hole"
        if kind in ("screw", "half_lap", "dowel") and feature_ids:
            appropriate_owners = {feature_map[fid][0] for fid in feature_ids if fid in feature_map and feature_map[fid][1].get("kind") == required_kind and feature_map[fid][1].get("role", "connection") == "connection"}
            if set(ids) - appropriate_owners:
                add("joint_feature_kind", f"{jid}：每个连接零件都需要对应的孔或槽。", ids)
        if kind in ("screw", "dowel") and valid_ids and all(pid in valid_geometry for pid in ids):
            holes = [(pid, f) for fid in feature_ids if fid in feature_map
                     for pid, f in [feature_map[fid]]
                     if pid in ids and f.get("kind") == "hole" and f.get("role", "connection") == "connection" and not _feature_error(part_map[pid], f)]
            for pid, feature in holes:
                matches = [(other, candidate) for other, candidate in holes
                           if other != pid and _holes_match(part_map[pid], feature, part_map[other], candidate, kind == "dowel")]
                if not matches:
                    add("joint_holes_misaligned", f"{jid}/{feature['id']}：没有另一个零件的同轴、深度段相接孔；木销还要求对孔直径一致。", [pid])
        hardware = joint.get("hardware", [])
        if kind in ("screw", "dowel") and not hardware:
            add("hardware_missing", f"{jid}：请指定螺钉/木销的规格和数量。", ids)
        for item in hardware:
            quantity = item.get("quantity")
            if not item.get("name") or not item.get("spec") or not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
                add("hardware_invalid", f"{jid}：五金需要名称、规格和正整数数量。", ids)
        if valid_ids and all(pid in valid_geometry for pid in ids):
            # AABB separation is a necessary condition only, never a complete fit check.
            bounds = {pid: _bounds(part_map[pid]) for pid in ids}
            touching = {pid: set() for pid in ids}
            for i, a in enumerate(ids):
                for b in ids[i + 1:]:
                    if all(bounds[a][0][axis] <= bounds[b][1][axis] + 0.5 and bounds[b][0][axis] <= bounds[a][1][axis] + 0.5 for axis in range(3)):
                        touching[a].add(b)
                        touching[b].add(a)
            if any(not neighbors for neighbors in touching.values()):
                add("joint_parts_separated", f"{jid}：连接零件的包围盒分离，请核对装配位置。", ids)
    if len(part_map) > 1:
        seen, pending = set(), [next(iter(part_map))]
        while pending:
            pid = pending.pop()
            if pid not in seen:
                seen.add(pid)
                pending.extend(adjacency[pid] - seen)
        if seen != set(part_map):
            add("assembly_disconnected", "装配连接图不连通，部分零件没有连接到主体。", sorted(set(part_map) - seen))
    unused = set(feature_map) - used_features
    if unused:
        add("features_unassigned", "以下孔槽尚未关联连接，请核对其用途：" + "、".join(sorted(unused)), severity="warning")
    add("structural_coverage", "承载、连接强度与稳定性：未计算。", severity="warning")
    add("fit_coverage", "孔轴配对阈值 0.5 mm；加工公差、去料后干涉与装配可达性需实物核对。", severity="warning")
    if project.get("fabrication_mode") == "self":
        add("self_workshop", "先用同批余料试钻和试装连接，再加工正式零件。", severity="info")
    elif project.get("fabrication_mode") == "shop":
        add("shop_handoff", "加工店制件：交付零件编号、木纹方向、加工面和孔槽表；加工店确认公差与工艺后再生产。", severity="info")
    checks.extend(hardware_checks(project))
    return checks


def draw_part_svg(part: Any) -> str:
    from app.workbench.drawings import draw_part_sheets
    return draw_part_sheets(_data(part), {})[0]["svg"]


def build_package(project: Any) -> dict:
    project = _data(project)
    checks = build_checks(project)
    from app.workbench.compact_drawings import draw_part_sheets, draw_joint_sheets
    from app.workbench.assembly_sheet import draw_assembly_sheets
    instances = resolve_hardware(project)
    drawing_sheets = draw_assembly_sheets(project, instances)
    drawing_sheets.extend(sheet for part in project.get("parts", []) for sheet in draw_part_sheets(part, project))
    drawing_sheets.extend(draw_joint_sheets(project, instances))
    ready = (
        not any(c["severity"] == "blocker" for c in checks)
        and project.get("confirmed_revision") is not None
        and project.get("confirmed_revision") == project.get("revision")
        and project.get("acknowledged_limits") is True
    )
    parts, materials = project.get("parts", []), project.get("materials") or {}
    hardware_totals: dict[tuple[str, str], int] = defaultdict(int)
    assembly_steps = []
    for index, joint in enumerate(project.get("joints", []), 1):
        for item in joint.get("hardware", []):
            quantity = item.get("quantity")
            if isinstance(quantity, int) and not isinstance(quantity, bool) and quantity > 0:
                hardware_totals[(str(item.get("name", "")), str(item.get("spec", "")))] += quantity
        assembly_steps.append({
            "order": index, "joint_id": joint.get("id"), "name": joint.get("name") or joint.get("id"), "kind": joint.get("kind"),
            "part_ids": deepcopy(joint.get("part_ids", [])),
            "feature_ids": deepcopy(joint.get("feature_ids", [])),
            "instruction": joint.get("assembly_note") or "连接加工与装配做法尚未补充。",
            "hardware": deepcopy(joint.get("hardware", [])),
            "confirmed": bool(joint.get("confirmed")),
        })
    return {
        "project_id": str(project.get("id", "")), "revision": project.get("revision"),
        "status": "ready" if ready else "draft",
        "fabrication_mode": project.get("fabrication_mode"), "checks": checks,
        "parts": deepcopy(parts), "joints": deepcopy(project.get("joints", [])),
        "materials": deepcopy(materials),
        "modules": deepcopy(project.get("modules", [])),
        "cut_list": [{
            "part_id": p.get("id"), "name": p.get("name"), "quantity": 1,
            "stock_size_mm": deepcopy(p.get("size_mm")),
            "material_id": p.get("material_id"),
            "material_name": (materials.get(p.get("material_id")) or {}).get("name"),
            "grain_axis": (materials.get(p.get("material_id")) or {}).get("grain_axis"),
            "outline_mm": deepcopy(p.get("outline_mm")), "plane_cuts": deepcopy(p.get("plane_cuts",[])), "features": deepcopy(p.get("features", [])),
        } for p in parts],
        "hardware": [{"name": name, "spec": spec, "quantity": quantity} for (name, spec), quantity in sorted(hardware_totals.items())],
        "hardware_instances": instances,
        "assembly_steps": assembly_steps,
        "assumptions": deepcopy(project.get("assumptions", [])),
        "evidence": deepcopy(project.get("evidence", [])),
        "scale": deepcopy(project.get("scale")),
        "coverage": check_coverage(),
        "drawings": drawing_sheets,
    }






def check_coverage() -> dict:
    return {
            "checked": ["零件尺寸与材料完整性", "简单平面轮廓与凸平面斜切", "孔槽加工面与边界", "显式斜孔入口、轴向、深度与非出入口孔壁边界", "连接引用与装配图连通", "螺钉/木销孔同轴与钻孔段相接", "连接零件包围盒明显分离", "发布版本与确认记录"],
            "not_checked": ["整椅承载与连接强度", "木材缺陷和湿度影响", "侧向稳定性、倾覆及疲劳", "孔槽加工公差与实际紧固配合", "加工后实体干涉", "装配可达性及加工工具适配", "人体舒适性"],
        }
