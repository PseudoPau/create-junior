"""Deterministic fitting for the six-board, floor-supported chair construction.

This compiler edits the current design, never replaces it with a sample. Unsupported
topology fails explicitly. Hole axes, mating planes and hardware anchors share the
engine coordinate convention; connection consent is invalidated by the store.
"""
from copy import deepcopy
from math import cos, sin, radians, isclose
import re
from typing import Literal
from pydantic import Field
from app.workbench.models import Record, Project
from app.workbench.engine import FACE_AXES, _rotation, _rotate, _bounds, _local_hole_axis, _holes_match, build_checks
from app.workbench.revisions import invalidate_connections

KEYS = ('seat_height_mm', 'seat_depth_mm', 'seat_width_mm', 'back_angle_deg')


class FitRequest(Record):
    expected_revision: int = Field(ge=1)
    key: Literal['seat_height_mm', 'seat_depth_mm', 'seat_width_mm', 'back_angle_deg']
    value: float = Field(ge=0, le=2000)


class RevisionRequest(Record):
    expected_revision: int = Field(ge=1)


def _inverse(matrix, vector):
    return [sum(matrix[j][i] * vector[j] for j in range(3)) for i in range(3)]


def _world(part, local):
    return [x + part['position_mm'][i] for i, x in enumerate(_rotate(_rotation(part), local))]


def _local(part, world):
    return _inverse(_rotation(part), [world[i] - part['position_mm'][i] for i in range(3)])


def _set_hole(part, feature, entry, direction=None):
    a, b, _ = FACE_AXES[feature['face']]
    feature['u_mm'] = entry[a] + part['size_mm'][a] / 2
    feature['v_mm'] = entry[b] + part['size_mm'][b] / 2
    if feature.get('entry_mm') is not None or direction is not None:
        feature['entry_mm'] = entry
        if direction is not None:
            feature['direction_local'] = direction


def _layout(project, module):
    parts = project['parts']
    seats = [p for p in parts if p['kind'] == 'seat_board']
    if len(seats) != 1:
        raise ValueError('目前需要一个明确的座板，才能联动修改椅子尺寸。')
    seat = seats[0]
    if any(abs(x) > 1e-5 for x in seat['rotation_deg']) or seat.get('outline_mm'):
        raise ValueError('当前支持水平矩形座板；这版座板需要先补充尺寸关联。')
    if any(p.get('outline_mm') for p in parts):
        raise ValueError('当前带轮廓的零件尚不支持自动人体适配。')
    attached = {pid for j in project['joints'] if seat['id'] in j['part_ids'] for pid in j['part_ids'] if pid != seat['id']}
    back = [p for p in parts if p['id'] in attached and -120 <= p['rotation_deg'][0] <= -90 and all(abs(x) < 1e-5 for x in p['rotation_deg'][1:])]
    sides = [p for p in parts if p['id'] in attached and abs(p['rotation_deg'][0] - 90) < 1e-5 and all(abs(x) < 1e-5 for x in p['rotation_deg'][1:])]
    if len(back) != 1 or len(sides) != 2 or len(parts) != 6:
        raise ValueError('这版构造尚未建立尺寸关联；目前支持两侧立板、落地靠背与底脚的六板椅。')
    affected = set(module.get('affected_part_ids', []))
    if not {p['id'] for p in [seat, back[0], *sides]} <= affected:
        raise ValueError('Module 没有关联到完整的座板、靠背与支撑板。')
    if any(p.get('plane_cuts') for p in [back[0], *sides]):
        raise ValueError('支撑板有额外斜切，需先补充关联规则。')
    top = seat['position_mm'][1] - seat['size_mm'][1] / 2
    if any(abs(_bounds(p)[0][1]) > .1 or abs(_bounds(p)[1][1] - top) > .1 for p in sides):
        raise ValueError('侧立板必须从地面连续支撑到座板底面，才能自动调整座高。')
    return seat, back[0], sides


def _resize_seat(seat, axis, value):
    delta = value - seat['size_mm'][axis]
    shift = [0., 0., delta / 2 if axis == 2 else 0.]
    old = deepcopy(seat)
    seat['size_mm'][axis] = value
    seat['position_mm'] = [x + shift[i] for i, x in enumerate(seat['position_mm'])]
    for feature, before in zip(seat['features'], old['features']):
        local, _ = _local_hole_axis(old, before)
        _set_hole(seat, feature, [local[i] - shift[i] for i in range(3)])
    for cut in seat.get('plane_cuts', []):
        cut['offset_mm'] -= sum(cut['normal_local'][i] * shift[i] for i in range(3))


def _height(project, seat, back, sides, value):
    delta = value - (seat['position_mm'][1] + seat['size_mm'][1] / 2)
    old = {p['id']: deepcopy(p) for p in [seat, back, *sides]}
    seat['position_mm'][1] += delta
    for side in sides:
        side['size_mm'][2] += delta
        side['position_mm'][1] += delta / 2
    # Extend the back downwards from its unchanged upper section after translation.
    # Its lower edge remains grounded and its seat connection follows the seat.
    matrix = _rotation(back)
    length_delta = delta / matrix[1][2]
    back['size_mm'][2] += length_delta
    offset = _rotate(matrix, [0, 0, length_delta / 2])
    back['position_mm'] = [back['position_mm'][i] + (delta if i == 1 else 0) - offset[i] for i in range(3)]
    upper_features = {fid for joint in project['joints'] if seat['id'] in joint['part_ids'] for fid in joint.get('feature_ids', [])}
    for part in [back, *sides]:
        for feature, before in zip(part['features'], old[part['id']]['features']):
            local, _ = _local_hole_axis(old[part['id']], before)
            world = _world(old[part['id']], local)
            if part is back or feature['id'] in upper_features:
                world[1] += delta
            _set_hole(part, feature, _local(part, world))


def _angle(project, seat, back, value):
    if not 0 <= value <= 25:
        raise ValueError('此板件连接的靠背角支持 0–25°；更大角度需要新的连接方案。')
    joints = [j for j in project['joints'] if set(j['part_ids']) == {seat['id'], back['id']}]
    if len(joints) != 1:
        raise ValueError('靠背与座板需要一处明确的连接才能调整角度。')
    joint = joints[0]
    nuts = [(hardware, instance) for hardware in joint['hardware'] if (hardware.get('geometry') or {}).get('kind') == 'barrel_nut' for instance in hardware.get('instances', [])]
    if not nuts or len(seat.get('plane_cuts', [])) != 1:
        raise ValueError('当前靠背角调整需要斜切贴合面与明确的横孔螺母锚点。')
    s, c = sin(radians(value)), cos(radians(value))
    thick, depth, back_thick = seat['size_mm'][1], seat['size_mm'][2], back['size_mm'][1]
    old_seat, old_back = deepcopy(seat), deepcopy(back)
    old_height = _bounds(back)[1][1] - _bounds(back)[0][1]
    back['rotation_deg'][0] = -90 - value
    back['size_mm'][2] = (old_height - s * back_thick) / c
    back['position_mm'][1] = old_height / 2
    pivot = _world(seat, [0, thick / 2, -depth / 2])
    back['position_mm'][2] = (s * (pivot[1] - back['position_mm'][1]) + c * pivot[2] - back_thick / 2) / c
    seat['plane_cuts'] = [{'normal_local': [0, -s, -c], 'offset_mm': c * depth / 2 - s * thick / 2}]
    features = {f['id']: f for f in seat['features']}
    old_features = {f['id']: f for f in old_seat['features']}
    bolt_lengths = set()
    for hardware, instance in nuts:
        if instance.get('part_id') != seat['id'] or instance.get('bore_part_id') != seat['id']:
            raise ValueError('横孔螺母必须明确锚定座板主孔和安装孔。')
        main = features[instance['bore_feature_id']]
        access = features[instance['feature_id']]
        candidates = [f for f in old_back['features'] if f['id'] in joint['feature_ids'] and _holes_match(old_seat, old_features[main['id']], old_back, f, False)]
        if len(candidates) != 1:
            raise ValueError('靠背主孔尚未与座板孔可靠配对，无法自动旋转。')
        radius = main['diameter_mm'] / 2
        station = min(35., (thick / 2 - radius * c - 1) / s) if s > 1e-6 else 35.
        if station < 12:
            raise ValueError('板厚不足以容纳此角度的主孔和横孔螺母，请增加板厚或减小角度。')
        y = -station * s
        x = _local_hole_axis(old_seat, old_features[main['id']])[0][0]
        z = -(seat['plane_cuts'][0]['offset_mm'] + s * y) / c
        entry, direction = [x, y, z], [0, s, c]
        _set_hole(seat, main, entry, direction)
        main['depth_mm'] = station + 12
        nut_center = [entry[i] + direction[i] * station for i in range(3)]
        nut_axis = [0, c, -s]
        distance = (nut_center[1] + thick / 2) / c
        nut_length = hardware['geometry']['length_mm']
        instance['offset_mm'] = distance - nut_length / 2
        if instance['offset_mm'] < 0:
            raise ValueError('横孔螺母无法完整埋入当前座板。')
        _set_hole(seat, access, [nut_center[i] - nut_axis[i] * distance for i in range(3)], nut_axis)
        access['depth_mm'] = distance + nut_length / 2
        other = next(f for f in back['features'] if f['id'] == candidates[0]['id'])
        world = _world(seat, entry)
        rear = [world[i] - direction[i] * back_thick for i in range(3)]
        _set_hole(back, other, _local(back, rear), [0, -1, 0])
        other['depth_mm'] = back_thick
        lengths = [length for length in [40, 50, 60, 70, 80, 90, 100] if back_thick + 1.6 + station + 3 <= length <= back_thick + 1.6 + main['depth_mm']]
        if not lengths:
            raise ValueError('当前角度与板厚没有可匹配的标准螺栓长度。')
        bolt_lengths.add(min(lengths))
    if len(bolt_lengths) != 1:
        raise ValueError('两处靠背连接需要不同螺栓长度，需单独编制连接方案。')
    selected_length = next(iter(bolt_lengths))
    for hardware in joint['hardware']:
        if (hardware.get('geometry') or {}).get('kind') == 'bolt':
            hardware['geometry']['length_mm'] = selected_length
            hardware['spec'] = re.sub(r'(?<=×)\s*\d+(?:\.\d+)?\s*mm', f' {selected_length} mm', hardware['spec'], count=1)


def _sample_reference_ranges(module):
    """Compatibility migration for the documented sample's illustrative adult ranges.

    No imported/custom manufacturing constraint is weakened. New sample data already
    labels these reference-only ranges recommended.
    """
    expected = {'seat_width_mm': (360, 520), 'seat_depth_mm': (180, 500), 'seat_height_mm': (380, 520)}
    if module.get('notes') != '模块目标来自样例流程输入；人体工学范围需要按实际使用者和专业依据复核。':
        return
    constraints = module.get('constraints', [])
    if len(constraints) == 3 and all(c.get('operator') == 'range' and (c.get('min_mm'), c.get('max_mm')) == expected.get(c['key']) for c in constraints):
        for constraint in constraints:
            constraint['priority'] = 'recommended'


def _sample_fabrication_notes(data, module, seat, angle):
    """Regenerate only the sample's compiler-owned instructions, retaining user notes."""
    if module.get('notes') != '模块目标来自样例流程输入；人体工学范围需要按实际使用者和专业依据复核。':
        return
    rules = [
        ('24mm为刨光后的净厚；', f"{seat['size_mm'][1]:g}mm为刨光后的净厚；座板后缘按本版C1剖面加工，靠背倾角{angle:g}°；按加工面的坐标与孔轴钻孔。"),
        ('钻孔工具：', f'钻孔工具：Ø6.5钻头、Ø10木工钻、Ø20平底钻、直角与{angle:g}°钻孔导向夹具、深度挡圈。'),
        ('横孔螺母为Ø10×14、M6居中螺纹；', f'横孔螺母为Ø10×14、M6居中螺纹；安装孔深度与端面沉入量按本版零件图，靠背连接使用{angle:g}°导向夹具。'),
    ]
    # Later fits update the already generated first instruction as well.
    data['assumptions'] = [next((replacement for prefix, replacement in rules
                                      if note.startswith(prefix)), note)
                                 for note in data.get('assumptions', [])]
    if data.get('scope_reason', '').startswith('六块24mm白蜡木板；'):
        data['scope_reason'] = f'六块24mm白蜡木板；座板后缘{angle:g}°平面斜切，显式孔轴与M6可拆装连接。'


def fit_preview(project: Project, module_id: str, key: str, value: float) -> dict:
    data = project.model_dump(mode='json')
    module = next((m for m in data['modules'] if m['id'] == module_id), None)
    if module is None:
        raise ValueError('找不到这个 Module。')
    seat, back, sides = _layout(data, module)
    current = {'seat_height_mm': seat['position_mm'][1] + seat['size_mm'][1] / 2, 'seat_width_mm': seat['size_mm'][0], 'seat_depth_mm': seat['size_mm'][2], 'back_angle_deg': -90 - back['rotation_deg'][0]}
    if key not in KEYS:
        raise ValueError('不支持的尺寸。')
    if key != 'back_angle_deg' and not 100 <= value <= 1200:
        raise ValueError('板件椅尺寸需在 100–1200 mm 内。')
    if not isclose(current[key], value, abs_tol=1e-5):
        if key == 'seat_height_mm':
            _height(data, seat, back, sides, value)
        elif key == 'back_angle_deg':
            _angle(data, seat, back, value)
        else:
            _resize_seat(seat, 0 if key == 'seat_width_mm' else 2, value)
    _sample_reference_ranges(module)
    module.setdefault('target', {}).update(current)
    module['target'][key] = value
    module.setdefault('confirmations', {})[key] = True
    module.setdefault('decisions', {})[key] = 'custom'
    module['status'] = 'target'
    _sample_fabrication_notes(data, module, seat, module['target']['back_angle_deg'])
    old_parts = {p.id: p.model_dump(mode='json') for p in project.parts}
    changed = [p['id'] for p in data['parts'] if p != old_parts[p['id']]]
    for joint in data['joints']:
        if set(changed).intersection(joint['part_ids']):
            joint['assembly_note'] = '本连接已随尺寸更新。按本版本零件图的孔口、孔轴、孔深和五金清单加工；对齐配对孔，先轻拧，校正后交替紧固。'
    # Editing a parameter neither establishes nor revokes the source's physical scale.
    data = Project.model_validate(data).model_dump(mode='json')
    invalidate_connections(project, data)
    checks = build_checks(data)
    # A human may consent to reusing connections; invalid geometry must be repaired first.
    failures = [issue for issue in checks if issue['severity'] == 'blocker' and issue['code'] not in {'joint_unconfirmed', 'scale_unconfirmed'}]
    if failures:
        raise ValueError('此尺寸暂不能应用：' + '；'.join(issue['message'] for issue in failures[:3]))
    patch = {key: data[key] for key in ['parts', 'joints', 'modules', 'assumptions', 'scope_reason']}
    return {'revision': project.revision, 'key': key, 'current_value': current[key], 'value': value, 'patch': patch, 'checks': checks, 'changed_part_ids': changed}
