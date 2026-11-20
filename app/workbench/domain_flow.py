"""Reference-preserving editing and body profile endpoints.

No anthropometric equation is treated as a manufacturing or preservation rule.
All accepted geometry still flows through the existing proposal transaction.
"""
from __future__ import annotations

from math import isclose
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import Field, model_validator

from app.workbench.models import BodyProfile, Module, Preservation, Project, Record
from app.workbench.measurements import DIMENSION_KEYS, dimension_items, legacy_edit
from app.workbench.module_fit import FitRequest, KEYS, _layout, fit_preview
from app.workbench.proposals import build_proposal
from app.workbench.store import RevisionConflict


LABELS = {'seat_height_mm': '座高', 'seat_width_mm': '座宽',
          'seat_depth_mm': '座板前后长度', 'back_angle_deg': '靠背角',
          'seat_tilt_deg': '座面倾角', 'seat_back_angle_deg': '座背夹角'}


class BaselineRequest(Record):
    expected_revision: int = Field(ge=1)
    source_revision: int | None = Field(default=None, ge=1)


class EditPreview(FitRequest):
    key: Literal['seat_height_mm', 'seat_depth_mm', 'seat_width_mm',
                 'back_angle_deg', 'seat_tilt_deg', 'seat_back_angle_deg']
    value: float = Field(ge=-90, le=2000, allow_inf_nan=False)
    decision: str = Field(default='custom', pattern='^(custom|adopt)$')
    allow_redesign: bool = False

    @model_validator(mode='after')
    def valid_dimension_value(self):
        if self.key == 'seat_tilt_deg':
            if self.value > 90:
                raise ValueError('座面倾角必须在 -90° 到 90° 之间')
        elif self.value < 0:
            raise ValueError('尺寸不能为负数')
        elif self.key == 'seat_back_angle_deg' and self.value > 180:
            raise ValueError('座背夹角必须在 0° 到 180° 之间')
        return self


class SaveProfile(BodyProfile):
    expected_revision: int = Field(ge=1)
    module_id: str


class ScaleAnchor(Record):
    expected_revision: int = Field(ge=1)
    length_mm: float = Field(gt=0, le=10000)
    note: str = Field(min_length=1, max_length=1000)


class RedesignRequest(Record):
    expected_revision: int = Field(ge=1)


def actual_dimensions(project: Project, module: Module) -> dict:
    """Return geometric measurements, never stale Module targets."""
    data = project.model_dump(mode='json')
    try:
        seat, back, _ = _layout(data, module.model_dump(mode='json'))
    except ValueError:
        seats = [part for part in data['parts'] if part['kind'] == 'seat_board']
        if len(seats) != 1 or any(abs(v) > 1e-5 for v in seats[0]['rotation_deg']):
            return {}
        seat, back = seats[0], None
    values = {'seat_height_mm': seat['position_mm'][1] + seat['size_mm'][1] / 2,
              'seat_width_mm': seat['size_mm'][0], 'seat_depth_mm': seat['size_mm'][2]}
    if back:
        values['back_angle_deg'] = -90 - back['rotation_deg'][0]
    return values


def baseline_project(store, project: Project) -> Project | None:
    if project.baseline_revision is None:
        return None
    path = store.directory(project.id) / 'versions' / f'{project.baseline_revision}.json'
    return Project.model_validate_json(path.read_text(encoding='utf-8')) if path.exists() else None


def verified_range(project: Project, key: str, *, legacy_back: bool = False) -> dict | None:
    limits = {rule.key: rule for rule in project.preservation.limits
              if project.preservation.status == 'verified' and rule.operator == 'range'}
    bound, offset = limits.get(key), 0
    if bound is None and legacy_back:
        bound, offset = limits.get('back_angle_deg'), 90
    return {'min': bound.min_mm + offset, 'max': bound.max_mm + offset} if bound else None


def compare_fit(project: Project, module: Module, baseline: Project | None, *, canonical: bool = False) -> dict:
    original_module = next((item for item in baseline.modules if item.id == module.id), None) if baseline else None
    if canonical:
        measured = dimension_items(project, module.id)
        original = {item['key']: item['current_value'] for item in dimension_items(baseline, module.id)} if original_module else {}
    else:
        values = actual_dimensions(project, module)
        original = actual_dimensions(baseline, original_module) if original_module else {}
        try:
            _layout(project.model_dump(mode='json'), module.model_dump(mode='json'))
            editable = True
        except ValueError:
            editable = False
        measured = [{'key': key, 'label': LABELS[key], 'unit': '°' if key.endswith('_deg') else 'mm',
                     'current_value': values.get(key), 'editable': editable} for key in KEYS]
    items = []
    for measurement in measured:
        key = measurement['key']
        # A legacy back angle is measured from vertical. Only the established
        # horizontal-seat compiler proves that adding 90 gives the included angle.
        legacy_back = canonical and key == 'seat_back_angle_deg' and measurement.get('legacy_key') == 'back_angle_deg'
        allowed_range = verified_range(project, key, legacy_back=legacy_back)
        reason = ('缺少腿长或实际坐姿依据，不用身高公式直接改变原椅子。' if key == 'seat_height_mm' else
                  '臀宽是身体数据，座面形态和活动余量仍需结合原椅子判断。' if key == 'seat_width_mm' else
                  '坐高不能直接推导座板前后长度，默认保留原设计。' if key == 'seat_depth_mm' else
                  '座面倾角与支撑和连接有关，默认保留原设计。' if key == 'seat_tilt_deg' else
                  '靠背角与原椅构造和连接有关，默认保留原设计。')
        if canonical and measurement['status'] == 'unknown':
            reason = measurement['reason']
        decision_key = 'back_angle_deg' if legacy_back else key
        items.append({**measurement, 'original_value': original.get(key),
                      'suggested_value': None, 'status': 'unknown', 'reason': reason,
                      'decision': module.decisions.get(decision_key), 'allowed_range': allowed_range})
        item = items[-1]
        if canonical:
            item['measurement_status'] = measurement['status']
            item['editable'] = measurement['capability'] == 'local_compiler'
        suggestion = next((entry for entry in module.suggestions if entry.key == key
                           and entry.anthropometry == module.anthropometry), None)
        suggestion_offset = 0
        if suggestion is None and canonical and key == 'seat_back_angle_deg':
            legacy_suggestion = next((entry for entry in module.suggestions if entry.key == 'back_angle_deg'
                                      and entry.anthropometry == module.anthropometry), None)
            if legacy_suggestion is not None:
                if legacy_back:
                    suggestion, suggestion_offset = legacy_suggestion, 90
                else:
                    item['reason'] += '旧靠背角建议缺少可转换的水平座面基准，不能视为座背夹角。'
        if suggestion is not None and (canonical or item['current_value'] is not None):
            value = suggestion.value + suggestion_offset
            item['suggested_value'] = value
            item['reason'] = suggestion.reason + '（AI 根据当前身体数据提出，尚非舒适性验证。）'
            if item['current_value'] is None:
                item['reason'] += '当前尺寸无法明确测量，不能核对或应用此建议。'
            elif isclose(value, item['current_value'], abs_tol=.01):
                item['status'] = 'unchanged'
            elif key != 'seat_height_mm' and not (allowed_range and allowed_range['min'] <= value <= allowed_range['max']):
                item['status'] = 'conflict'
                item['reason'] += '此项没有已校核的保型范围，需要明确作为改款。'
            elif canonical and item['capability'] != 'local_compiler':
                item['reason'] += '需要 Agent 返回板件、孔位和连接的关联修改后再核对。'
            else:
                try:
                    edit_key, edit_value = legacy_edit(project, module.id, key, value) if canonical else (key, value)
                    fit_preview(project, module.id, edit_key, edit_value)
                    item['status'] = 'suggested'
                except ValueError as error:
                    item['status'] = 'conflict'
                    item['reason'] = str(error)
            if canonical and item['capability'] != 'local_compiler' and item['status'] == 'conflict':
                item['reason'] += '此构造还需要 Agent 返回关联修改，不能在本地直接应用。'
    return {'revision': project.revision, 'baseline_revision': project.baseline_revision,
            'summary': '已保存身体数据。保持原椅子，可请 AI 结合参考提出调整，也可直接修改模型尺寸。',
            'items': items}


def create_domain_router(store_source):
    """Accept a store or a callable, keeping test and runtime stores consistent."""
    router = APIRouter(prefix='/api/workbench')

    def store():
        return store_source() if callable(store_source) else store_source

    def load(project_id):
        try:
            return store().load(str(project_id))
        except FileNotFoundError:
            raise HTTPException(404, '找不到项目')

    def change(project_id, expected, patch):
        try:
            return store().change(str(project_id), expected, patch)
        except RevisionConflict as error:
            raise HTTPException(409, str(error))
        except ValueError as error:
            raise HTTPException(422, str(error))

    def module_for(project, module_id):
        result = next((module for module in project.modules if module.id == module_id), None)
        if result is None:
            raise HTTPException(404, '找不到这个 Module')
        return result

    def with_advice(project):
        from app.workbench.design_runs import DesignRuns
        advice = DesignRuns(store()).current_advice(project)
        if advice is not None:
            return project.model_copy(update={'modules': [Module.model_validate(item)
                for item in advice]}), advice
        return project, None

    @router.get('/projects/{project_id}/baseline')
    def get_baseline(project_id: UUID):
        project = load(project_id)
        return {'revision': project.revision, 'baseline_revision': project.baseline_revision,
                'baseline': baseline_project(store(), project)}

    @router.post('/projects/{project_id}/baseline', response_model=Project)
    def set_baseline(project_id: UUID, body: BaselineRequest):
        with store().lock:
            project = load(project_id)
            if project.revision != body.expected_revision:
                raise HTTPException(409, '设计已变化，请刷新后选择原版')
            if project.baseline_revision is not None:
                if body.source_revision not in (None, project.baseline_revision):
                    raise HTTPException(409, '原版基线已经建立，不能被后续修改覆盖')
                return project
            revision = body.source_revision or project.revision
            path = store().directory(project.id) / 'versions' / f'{revision}.json'
            if not path.exists():
                raise HTTPException(404, '找不到这个历史版本')
            original = Project.model_validate_json(path.read_text(encoding='utf-8'))
            if not original.parts:
                raise HTTPException(422, '先形成模型，再建立原版基线')
            preservation = project.preservation.model_dump(mode='json')
            if not preservation['features']:
                preservation = Preservation(
                    status='inferred', source_ids=[reference.id for reference in original.references],
                    features=['保留原版的部件组成及连接关系', '保留座面轮廓比例和靠背方向'],
                    adjustable_keys=['seat_height_mm'],
                    note='按已采用原版建立对照。座高可沿现有支撑联动；其他尺寸尚无经校核的保型范围。'
                ).model_dump(mode='json')
            return change(project_id, project.revision,
                          {'baseline_revision': revision, 'preservation': preservation})

    @router.get('/projects/{project_id}/modules/{module_id}/comparison')
    def comparison(project_id: UUID, module_id: str, canonical: bool = False):
        project = load(project_id)
        project, advice = with_advice(project)
        result = compare_fit(project, module_for(project, module_id), baseline_project(store(), project), canonical=canonical)
        result['advice_modules'] = advice
        return result

    @router.post('/projects/{project_id}/modules/{module_id}/edit-preview')
    def edit_preview(project_id: UUID, module_id: str, body: EditPreview):
        with store().lock:
            project = load(project_id)
            if project.revision != body.expected_revision:
                raise HTTPException(409, '设计已变化，保留输入并重新预览')
            module = module_for(project, module_id)
            # Normalize before preservation checks and compilation. Existing
            # module targets/decisions keep the compiler's legacy angle meaning.
            edit_key, edit_value = body.key, body.value
            if body.key in DIMENSION_KEYS:
                try:
                    edit_key, edit_value = legacy_edit(project, module_id, body.key, body.value)
                except ValueError as error:
                    raise HTTPException(422, {'code': 'agent_required', 'message': str(error),
                        'module_id': module_id, 'key': body.key, 'requested_value': body.value})
            original = baseline_project(store(), project)
            original_module = next((item for item in original.modules if item.id == module_id), None) if original else None
            dimensions = actual_dimensions(project, module)
            baseline_dimensions = actual_dimensions(original, original_module) if original_module else {}
            preserved_value = baseline_dimensions.get(edit_key, dimensions.get(edit_key))
            differs = preserved_value is not None and not isclose(preserved_value, edit_value, abs_tol=.01)
            bounds = verified_range(project, body.key, legacy_back=body.key == 'seat_back_angle_deg')
            within_verified = bool(bounds and bounds['min'] <= body.value <= bounds['max'])
            if (project.design_intent != 'redesign' and differs and edit_key != 'seat_height_mm'
                    and not within_verified and not body.allow_redesign):
                raise HTTPException(409, {'code': 'preservation_decision',
                    'message': '这项尺寸没有已校核的保型范围。可以保持原样，或明确作为改款预览；原版仍会保留。',
                    'key': body.key, 'original_value': preserved_value + 90 if body.key == 'seat_back_angle_deg' else preserved_value,
                    'requested_value': body.value,
                    'can_redesign': True})
            try:
                advised_project, _ = with_advice(project)
                result = fit_preview(advised_project, module_id, edit_key, edit_value)
                patch = result['patch']
                next(module for module in patch['modules'] if module['id'] == module_id)['decisions'][edit_key] = body.decision
                if body.allow_redesign:
                    patch['design_intent'] = 'redesign'
                proposal = build_proposal(project, f"{LABELS[body.key]}调整为 {body.value:g} {'°' if body.key.endswith('_deg') else 'mm'}" + ('；作为改款保留原版。' if body.allow_redesign else '。'), patch)
            except ValueError as error:
                raise HTTPException(422, str(error))
            proposal['source'] = 'dimension_edit'
            proposal['edit'] = {'module_id': module_id, 'key': body.key, 'value': body.value,
                                'current_value': result['current_value'] + 90 if body.key == 'seat_back_angle_deg' else result['current_value']}
            store().save_proposal(project.id, proposal)
            return proposal

    @router.get('/profile')
    def get_profile():
        path = store().root / 'profile.json'
        return BodyProfile.model_validate_json(path.read_text(encoding='utf-8')) if path.exists() else None

    @router.post('/projects/{project_id}/proposal/{proposal_id}/redesign')
    def redesign_preview(project_id: UUID, proposal_id: UUID, body: RedesignRequest):
        with store().lock:
            project = load(project_id)
            if project.revision != body.expected_revision:
                raise HTTPException(409, '设计已变化，请重新预览')
            try:
                original = store().proposal(project.id, str(proposal_id))
            except FileNotFoundError:
                raise HTTPException(404, '找不到这版修改')
            if original.get('base_revision') != project.revision or original.get('status') != 'ready':
                raise HTTPException(409, '这版修改已经过期，请重新预览')
            proposal = build_proposal(project, original['summary'] + '；作为改款保留原版。',
                                      {**original['patch'], 'design_intent': 'redesign'},
                                      purpose=original.get('purpose', 'design'))
            proposal['source'] = 'user_redesign'
            if original.get('run_id'):
                proposal['run_id'] = original['run_id']
            store().save_proposal(project.id, proposal)
            return proposal

    @router.post('/projects/{project_id}/profile', response_model=Project)
    def save_profile(project_id: UUID, body: SaveProfile):
        with store().lock:
            project = load(project_id)
            module_for(project, body.module_id)
            profile = BodyProfile.model_validate(body.model_dump(exclude={'expected_revision', 'module_id'}))
            modules = project.model_dump(mode='json')['modules']
            module = next(module for module in modules if module['id'] == body.module_id)
            prior_profile = {key: module['anthropometry'].get(key) for key in
                             ('stature_mm', 'sitting_height_mm', 'hip_breadth_mm', 'posture')}
            next_profile = {'stature_mm': body.height_mm, 'sitting_height_mm': body.sitting_height_mm,
                            'hip_breadth_mm': body.hip_width_mm, 'posture': body.posture}
            if prior_profile != next_profile:
                module['decisions'] = {key: decision for key, decision in module.get('decisions', {}).items()
                                       if decision != 'keep'}
            module['anthropometry'].update(stature_mm=body.height_mm, sitting_height_mm=body.sitting_height_mm,
                                          hip_breadth_mm=body.hip_width_mm, posture=body.posture,
                                          measurement_source='user_input')
            module['posture'] = body.posture
            module['status'] = 'needs_review'
            # Changing the profile never changes adopted dimensions or previous decisions.
            project = change(project_id, body.expected_revision,
                             {'modules': modules, 'profile_snapshot': profile.model_dump(mode='json')})
            store().atomic_json(store().root / 'profile.json', profile.model_dump(mode='json'))
            return project

    @router.post('/projects/{project_id}/scale-anchor', response_model=Project)
    def set_scale(project_id: UUID, body: ScaleAnchor):
        with store().lock:
            project = load(project_id)
            lengths = [value for part in project.parts for value in part.size_mm]
            for module in project.modules:
                lengths.extend(value for key, value in actual_dimensions(project, module).items() if key.endswith('_mm'))
            if not any(isclose(body.length_mm, value, abs_tol=.1) for value in lengths):
                raise HTTPException(422, '实测尺寸与当前模型不一致，请先调整对应模型尺寸，再采用尺度依据。')
            return change(project_id, body.expected_revision, {'scale': {
                'kind': 'reference', 'length_mm': body.length_mm, 'confirmed': True, 'note': body.note}})

    return router
