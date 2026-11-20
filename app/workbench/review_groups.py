"""Read-only projections for the staged Junior review flow."""
from __future__ import annotations

import hashlib
import json
from os.path import commonprefix
from collections import defaultdict
from itertools import product
from typing import Any
from app.workbench.engine import FACE_AXES, _rotation, _rotate, _local_hole_axis


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): _dump(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_dump(v) for v in value]
    return value


def _canonical(value: Any) -> str:
    return json.dumps(_dump(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()[:16]


def _material(project: dict[str, Any], material_id: str) -> dict[str, Any]:
    value = (project.get("materials") or {}).get(material_id, {})
    return _dump(value) if value else {"id": material_id, "missing": True}




def _rounded(values):
    return [0.0 if abs(value) < .0000005 else round(value, 6) for value in values]


def _cycle(points):
    choices = []
    for vertices in (points, list(reversed(points))):
        choices.extend(vertices[i:] + vertices[:i] for i in range(len(vertices)))
    return min(choices, key=_canonical) if choices else []


def _feature(part, feature, point, vector):
    entry, direction = _local_hole_axis(part, feature)
    definition = {key: feature.get(key) for key in
                  ('kind', 'role', 'diameter_mm', 'width_mm', 'length_mm', 'depth_mm')}
    definition.update(entry=point(entry), direction=vector(direction))
    if feature['kind'] == 'slot':
        a, b, _ = FACE_AXES[feature['face']]
        corners = []
        for u, v in ((0, 0), (feature.get('width_mm') or 0, 0),
                     (feature.get('width_mm') or 0, feature.get('length_mm') or 0),
                     (0, feature.get('length_mm') or 0)):
            corner = list(entry); corner[a] += u; corner[b] += v
            corners.append(point(corner))
        definition['outline'] = _cycle(corners)
        definition.pop('entry')
    return definition


def _geometry(project, part, point, vector):
    size = part['size_mm']
    corners = [point([size[i] * signs[i] / 2 for i in range(3)])
               for signs in product((-1, 1), repeat=3)]
    cuts = [{'normal': vector(cut['normal_local']),
             'point': point([axis * cut['offset_mm'] for axis in cut['normal_local']])}
            for cut in part.get('plane_cuts', [])]
    outline = part.get('outline_mm')
    contours = [_cycle([point([x-size[0]/2, y, z-size[2]/2]) for x, z in outline])
                for y in (-size[1]/2, size[1]/2)] if outline else None
    features = [_feature(part, feature, point, vector) for feature in part.get('features', [])]
    return {'kind': part.get('kind'), 'material_id': part.get('material_id'),
            'material': _material(project, part.get('material_id', '')),
            'box': sorted(corners), 'contours': sorted(contours, key=_canonical) if contours else None,
            'cuts': sorted(cuts, key=_canonical), 'features': sorted(features, key=_canonical)}


def _part_signature(project, part):
    variants = []
    # Board poses are assembly data. Manufacture equivalence compares complete
    # local solids and machining, including mirrored features, never IDs/names.
    for signs in product((-1, 1), repeat=3):
        transform = lambda value: _rounded([value[i] * signs[i] for i in range(3)])
        variants.append(_geometry(project, part, transform, transform))
    return min(variants, key=_canonical)


def _joint_signature(project, joint, parts_by_id):
    members = [parts_by_id.get(pid) for pid in joint.get('part_ids', [])]
    if not members or any(part is None for part in members):
        return {'invalid_joint': joint.get('id')}
    center = [sum(p['position_mm'][i] for p in members)/len(members) for i in range(3)]
    variants = []
    # Reflect the entire relative assembly in a vertical plane, not its members
    # independently. This proves symmetrical connections without chair IDs.
    for sx, sz in product((-1, 1), repeat=2):
        signs = (sx, 1, sz)
        shapes, anchors = {}, {}
        for part in members:
            matrix = _rotation(part)
            def vector(value, matrix=matrix):
                rotated = _rotate(matrix, value)
                return _rounded([rotated[i]*signs[i] for i in range(3)])
            def point(value, matrix=matrix, part=part):
                rotated = _rotate(matrix, value)
                return _rounded([(rotated[i]+part['position_mm'][i]-center[i])*signs[i]
                                 for i in range(3)])
            shape = _geometry(project, part, point, vector)
            shapes[part['id']] = shape
            for feature in part.get('features', []):
                anchors[(part['id'], feature['id'])] = {
                    'part': shape, 'feature': _feature(part, feature, point, vector)}

        def referenced(feature_id, part_id=None):
            found = [value for (pid, fid), value in anchors.items()
                     if fid == feature_id and (part_id is None or pid == part_id)]
            return sorted(found, key=_canonical) if found else {'missing': feature_id, 'part_id': part_id}

        hardware = []
        for item in joint.get('hardware', []):
            hardware.append({'name': item.get('name'), 'spec': item.get('spec'),
                             'quantity': item.get('quantity'), 'geometry': item.get('geometry'),
                             'instances': sorted([{'anchor': referenced(instance.get('feature_id'), instance.get('part_id')),
                                 'offset_mm': instance.get('offset_mm', 0),
                                 'bore': referenced(instance.get('bore_feature_id'), instance.get('bore_part_id'))
                                         if instance.get('bore_feature_id') else None}
                                 for instance in item.get('instances', [])], key=_canonical)})
        variants.append({'kind': joint.get('kind'), 'parts': sorted(shapes.values(), key=_canonical),
                         'features': sorted([referenced(fid) for fid in joint.get('feature_ids', [])], key=_canonical),
                         'hardware': sorted(hardware, key=_canonical)})
    return min(variants, key=_canonical)


def _part_dimensions(part: dict[str, Any]) -> dict[str, Any]:
    size = list(part.get("size_mm", (0, 0, 0)))
    while len(size) < 3:
        size.append(0)
    thin = min(range(3), key=lambda i: (size[i], i != 1, i))
    length = 2 if thin != 2 else 0
    width = next(i for i in range(3) if i not in (thin, length))
    return {'length_mm': size[length], 'width_mm': size[width], 'thickness_mm': size[thin],
            'axes': {'length': 'local_'+'xyz'[length], 'width': 'local_'+'xyz'[width],
                     'thickness': 'local_'+'xyz'[thin]}}


def board_dimensions(part: Any) -> dict[str, Any]:
    """Stock envelope dimensions; a planar trim does not shrink the raw blank."""
    return _part_dimensions(_dump(part))


def _group_name(members, fallback):
    names = [str(member.get('name') or '') for member in members]
    if len(set(names)) == 1:
        return names[0] or fallback
    prefix = commonprefix(names)
    suffix = commonprefix([name[len(prefix):][::-1] for name in names])[::-1]
    shared = (prefix+suffix).strip(' -_/·')
    return shared if len(shared) >= 2 else ' / '.join(names) or fallback


def _part_group(project: dict[str, Any], members: list[dict[str, Any]], index: int) -> dict[str, Any]:
    ids = sorted(str(part["id"]) for part in members)
    # Equivalence can merge mirrored pieces; consent still belongs to each
    # piece's actual handed machining and must reopen when that changes.
    signature = [_geometry(project, part, _rounded, _rounded)
                 for part in sorted(members, key=lambda part: part['id'])]
    return {
        "id": "board-" + _fingerprint({"members": ids}),
        "part_ids": ids,
        "name": _group_name(members, "板件组 " + str(index + 1)),
        "dimensions": _part_dimensions(members[0]),
        "quantity": len(members),
        "material_id": str(members[0].get("material_id", "")),
        "fingerprint": _fingerprint(signature),
    }




def _node_group(project: dict[str, Any], members: list[dict[str, Any]], index: int,
                parts_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ids = sorted(str(joint["id"]) for joint in members)
    part_ids = sorted({str(part_id) for joint in members for part_id in joint.get("part_ids", [])})
    notes = {joint['id']: joint.get('assembly_note', '') for joint in members}
    physical = []
    for joint in sorted(members, key=lambda joint: joint['id']):
        parts = [parts_by_id[pid] for pid in joint['part_ids'] if pid in parts_by_id]
        center = [sum(part['position_mm'][i] for part in parts)/len(parts) if parts else 0 for i in range(3)]
        physical.append({'joint': {key: value for key, value in joint.items() if key not in ('name', 'confirmed')},
            'parts': {part['id']: {'geometry': _geometry(project, part, _rounded, _rounded),
                'rotation': part['rotation_deg'],
                'relative_position': _rounded([part['position_mm'][i]-center[i] for i in range(3)])}
                for part in parts}})
    signature = {'geometry': physical, 'assembly_notes': notes}
    return {
        "id": "node-" + _fingerprint({"members": ids}),
        "joint_ids": ids, "part_ids": part_ids,
        "name": _group_name(members, "连接节点组 " + str(index + 1)),
        "kind": members[0].get("kind"), "quantity": len(members),
        "assembly_notes": notes,
        "fingerprint": _fingerprint(signature),
    }


def review_groups(project: Any) -> dict[str, list[dict[str, Any]]]:
    """Project board and node equivalence groups without mutating the design."""
    data = _dump(project)
    parts = [dict(value) for value in data.get("parts", [])]
    joints = [dict(value) for value in data.get("joints", [])]
    parts_by_id = {str(part.get("id")): part for part in parts}
    board_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for part in parts:
        board_buckets[_canonical(_part_signature(data, part))].append(part)
    board_groups = [_part_group(data, members, i) for i, members in enumerate(board_buckets.values())]
    node_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for joint in joints:
        node_buckets[_canonical(_joint_signature(data, joint, parts_by_id))].append(joint)
    node_groups = [_node_group(data, members, i, parts_by_id) for i, members in enumerate(node_buckets.values())]
    return {"board_groups": board_groups, "node_groups": node_groups}


def review_group_fingerprint(group: dict[str, Any]) -> str:
    return str(group.get("fingerprint") or _fingerprint(group))
