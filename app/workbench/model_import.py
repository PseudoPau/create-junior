"""Open a native exported design as a new local project, never overwrite it."""
from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from app.workbench.models import Project, now


router = APIRouter(prefix='/api/workbench')
MAX_MODEL_BYTES = 2 * 1024 * 1024


def import_native_model(store, payload: bytes) -> Project:
    """Trust the design geometry as editable input, not imported validation flags."""
    source = Project.model_validate_json(payload)
    if not source.parts:
        raise ValueError('这个文件没有可编辑部件，请选择加工包中的 design.json。')
    data = source.model_dump(mode='json')
    source_revision = source.revision
    data.update(id=str(uuid4()), revision=1, updated_at=now(), baseline_revision=None,
                confirmed_revision=None, acknowledged_limits=False, review_state=None)
    data['name'] = (source.name[:112] + ' · 导入副本')[:120]
    missing = []
    for reference in data['references']:
        if reference['kind'] in {'image', 'document'}:
            missing.append(reference['name'])
            reference.update(kind='note', url='', text=(
                f"导入模型原先引用的附件：{reference['name']}。文件未包含在 design.json 中，"
                f"本项目尚未读取该附件；原资料编号 {reference['id']} 保留用于追溯。请重新添加原图片或图纸。"
            )[:8000])
    missing_ids = {reference.id for reference in source.references if reference.kind in {'image', 'document'}}
    for evidence in data['evidence']:
        if missing_ids.intersection(evidence['source_ids']):
            evidence['statement'] = '导入的历史记录，原附件未随文件提供，尚未重新核对：' + evidence['statement']
            evidence['status'] = 'unknown'
    if data.get('scale'):
        data['scale'].update(kind='target', confirmed=False,
                             note='导入模型保留的尺寸，需核对实际尺度。原记录：' + data['scale'].get('note', ''))
    for joint in data['joints']:
        joint['confirmed'] = False
    for module in data['modules']:
        module.update(status='needs_review', confirmations={}, decisions={}, suggestions=[])
    preservation = data['preservation']
    if preservation['status'] == 'verified':
        preservation['status'] = 'inferred'
    preservation['note'] = ('导入的保型说明尚未重新校核。' + preservation.get('note', ''))[:2000]
    data['scope_reason'] += (f" 模型文件由源版本 v{source_revision} 导入为独立副本；原版基线和发布确认未复制。"
                             + (' 原参考附件缺失，已保留追溯说明。' if missing else ''))
    project = Project.model_validate(data)
    with store.lock:
        return store.save(project)


@router.post('/projects/import', response_model=Project)
async def open_model(request: Request):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_MODEL_BYTES:
            raise HTTPException(413, '模型文件最多 2 MB。')
    try:
        from app.workbench.api import workbench_store
        return import_native_model(workbench_store, bytes(raw))
    except ValidationError as error:
        locations = ['.'.join(str(part) for part in item['loc']) for item in error.errors()[:8]]
        raise HTTPException(422, '请选择完整的 Junior design.json 模型文件；字段不符合契约：' + '、'.join(locations)) from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
