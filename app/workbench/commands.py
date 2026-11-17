"""Bounded local commands and their durable conversation records."""
from __future__ import annotations
import json
import re
from uuid import uuid4
from typing import Literal
from pydantic import Field
from app.workbench.models import Command, Project, now


class Interaction(Command):
    selected_part_id: str | None = Field(default=None, max_length=80)
    stage: Literal["reference", "fit", "manufacturing"] = "manufacturing"


def dimension_command(project: Project, text: str, selected_part_id: str | None):
    """Return a literal dimension edit only when its coordinate meaning is explicit."""
    text = text.strip().rstrip('。.!！')
    targets = [(part, re.escape(part.name)) for part in project.parts]
    selected = next((p for p in project.parts if p.id == selected_part_id), None)
    if selected:
        targets.append((selected, r'(?:选中部件|这个部件|当前部件)'))
    seats = [p for p in project.parts if p.kind == 'seat_board']
    if len(seats) == 1 and seats[0] not in [p for p, _ in targets if p.name == '座板']:
        targets.append((seats[0], '座板'))
    matches = []
    for part, target in targets:
        match = re.fullmatch(r'(?:请)?(?:把)?' + target + r'\s*(?:的)?\s*(X|Y|Z|宽度|座宽)\s*(?:尺寸)?\s*(?:改为|改成|设为|设置为|=)\s*(\d+(?:\.\d+)?)\s*(?:mm|毫米)', text, re.I)
        if match:
            label = match.group(1).upper()
            if label not in 'XYZ' and part.kind != 'seat_board':
                return None
            axis = 'XYZ'.index(label) if label in 'XYZ' else 0
            matches.append((part, axis, float(match.group(2))))
    if len({(p.id, axis, value) for p, axis, value in matches}) != 1:
        return None
    part, axis, value = matches[0]
    if not 1 <= value <= 10000:
        return {'reply': '尺寸请输入 1–10000 mm。'}
    old = part.size_mm[axis]
    if abs(value - old) < 1e-6:
        return {'reply': f'{part.name}的局部 {"XYZ"[axis]} 尺寸已经是 {value:g} mm。'}
    # Editing this extent must not silently relocate a mating face or rescale a contour.
    face_axes = {'top': (0, 2, 1), 'bottom': (0, 2, 1), 'front': (0, 1, 2), 'back': (0, 1, 2), 'left': (2, 1, 0), 'right': (2, 1, 0)}
    if part.outline_mm or any(abs(c.normal_local[axis]) > 1e-6 for c in part.plane_cuts) or any(face_axes[f.face][2] == axis for f in part.features):
        return None
    parts = [p.model_dump(mode='json') for p in project.parts]
    changed = next(p for p in parts if p['id'] == part.id)
    changed['size_mm'][axis] = value
    for feature in changed['features']:
        a, b, _ = face_axes[feature['face']]
        if axis == a:
            feature['u_mm'] += (value-old)/2
        if axis == b:
            feature['v_mm'] += (value-old)/2
    summary = f'{part.name} · 局部 {"XYZ"[axis]}：{old:g} → {value:g} mm。部件中心与现有孔轴位置保留。'
    scale = {'kind': 'target', 'confirmed': False, 'length_mm': value,
             'note': f'本次采用 {part.name} 局部 {"XYZ"[axis]} 尺寸 {value:g} mm；其余部件尺寸沿用模型。'}
    return {'summary': summary, 'patch': {'parts': parts, 'scale': scale}, 'part_id': part.id}


def read_records(store, project_id):
    path = store.directory(project_id) / 'conversation.json'
    return json.loads(path.read_text(encoding='utf-8')).get('records', []) if path.exists() else []


def append_record(store, project_id, record):
    records = read_records(store, project_id)
    records.append(record)
    store.atomic_json(store.directory(project_id) / 'conversation.json', {'records': records[-100:]})


def interaction_record(project, text, reply, **extra):
    return {'id': str(uuid4()), 'text': text, 'reply': reply, 'created_at': now(),
            'base_revision': project.revision, **extra}


def mark_accepted(store, project_id, proposal, revision):
    mark_proposal_records(store, project_id, proposal['id'], status='completed', result_revision=revision)


def mark_proposal_records(store, project_id, proposal_id, **changes):
    records = read_records(store, project_id)
    changed = False
    for record in records:
        if record.get('proposal_id') == proposal_id:
            record.update(**changes)
            changed = True
    if changed:
        store.atomic_json(store.directory(project_id) / 'conversation.json', {'records': records})


def history(store, project):
    records = read_records(store, project.id)
    try:
        latest = store.proposal(project.id)
    except FileNotFoundError:
        latest = None
    for record in records:
        if record.get('status') == 'ready':
            if record['base_revision'] != project.revision:
                record['status'] = 'stale'
            elif latest and record.get('proposal_id') != latest.get('id'):
                record['status'] = 'superseded'
    directory = store.directory(project.id) / 'preparation'
    current_path = directory / 'request.json'
    current = json.loads(current_path.read_text(encoding='utf-8')) if current_path.exists() else None
    for path in sorted((directory / 'requests').glob('*.json'), key=lambda x: x.stat().st_mtime, reverse=True)[:100]:
        req = json.loads(path.read_text(encoding='utf-8'))
        status = req.get('status', 'pending')
        reply = '已保存。回到当前聊天说“处理 Junior 请求”；方案返回后会出现在这里。'
        proposal_id = req.get('proposal_id')
        if status == 'cancelled':
            reply = req.get('proposal_summary') or '已取消这次候选。'
        elif status == 'completed':
            reply = f'已采用方案，更新到 v{req["result_revision"]}。'
        elif req['base_revision'] != project.revision:
            status, reply = 'stale', '设计已有新版本；再次发送时会带入最新模型。'
        elif not current or current['id'] != req['id']:
            status, reply = 'superseded', '已并入后续请求。'
        elif latest and latest.get('request_id') == req['id'] and latest.get('base_revision') == project.revision and latest.get('status') == 'ready':
            status, reply, proposal_id = 'ready', latest['summary'], latest['id']
        elif (status == 'pending' and latest and latest.get('request_id') == req['id']
              and latest.get('base_revision') == project.revision and latest.get('status') == 'cancelled'
              and req.get('last_declined_proposal_id') == latest['id']):
            status, reply, proposal_id = 'revision_requested', '这版方案未采用，需求仍保留。可以补充修改方向。', latest['id']
        records.append({'id': req['id'], 'request_id': req['id'], 'text': req.get('text') or '整理加工方案',
                        'reply': reply, 'status': status, 'kind': 'handoff', 'created_at': req['created_at'],
                        'base_revision': req['base_revision'], 'proposal_id': proposal_id,
                        'result_revision': req.get('result_revision')})
    return sorted(records, key=lambda r: r['created_at'])[-100:]
