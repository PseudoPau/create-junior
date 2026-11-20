"""Board-group edits reuse the dimension compiler and proposal transaction."""
from math import isclose

from app.workbench.models import Project
from app.workbench.module_fit import _layout, fit_preview
from app.workbench.proposals import build_proposal


def board_edit_preview(project: Project, group: dict, request: dict) -> dict:
    dimensions = group['dimensions']
    changed = {key: request[key] for key in ('length_mm', 'width_mm', 'thickness_mm')
               if not isclose(request[key], dimensions[key], abs_tol=.001)}
    material = request.get('material_id') or group['material_id']
    if material not in project.materials:
        raise ValueError('需要先定义材料属性与纹理方向，再生成关联的板件方案。')
    if 'thickness_mm' in changed:
        raise ValueError('板厚变化需要重新计算相接板件、孔轴和五金；请让 AI 返回关联方案。')
    working = project
    if changed:
        matches = []
        for module in project.modules:
            try:
                seat, back, sides = _layout(project.model_dump(mode='json'), module.model_dump(mode='json'))
            except ValueError:
                continue
            members = set(group['part_ids'])
            if members == {seat['id']}:
                edits = [('seat_depth_mm' if key == 'length_mm' else 'seat_width_mm', value)
                         for key, value in changed.items()]
            elif members == {side['id'] for side in sides} and set(changed) == {'length_mm'}:
                edits = [('seat_height_mm', changed['length_mm'] + seat['size_mm'][1])]
            else:
                continue
            matches.append((module.id, edits))
        if len(matches) != 1:
            raise ValueError('这组板件尚无已验证的尺寸关联；请让 AI 一并调整板件、孔位和节点。')
        module_id, edits = matches[0]
        for key, value in edits:
            result = fit_preview(working, module_id, key, value)
            working = Project.model_validate({**working.model_dump(mode='json'), **result['patch']})
    data = working.model_dump(mode='json')
    for part in data['parts']:
        if part['id'] in group['part_ids']:
            part['material_id'] = material
    patch = {key: data[key] for key in ('parts', 'joints', 'modules', 'assumptions', 'scope_reason')
             if data[key] != project.model_dump(mode='json')[key]}
    if request.get('allow_redesign'):
        patch['design_intent'] = 'redesign'
    summary = f"{group['name']}（{group['quantity']} 件）调整为 {request['length_mm']:g} × {request['width_mm']:g} × {request['thickness_mm']:g} mm。"
    proposal = build_proposal(project, summary, patch, purpose='manufacturing')
    proposal['source'] = 'board_edit'
    proposal['edit'] = {'group_id': group['id'], 'part_ids': group['part_ids'], 'dimensions': {
        key: request[key] for key in ('length_mm', 'width_mm', 'thickness_mm')}}
    return proposal
