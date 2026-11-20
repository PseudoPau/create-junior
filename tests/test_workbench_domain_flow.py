"""Design choice, source scale and geometric validity are separate facts."""
from copy import deepcopy

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.workbench.demo import cafe_candidate
from app.workbench.domain_flow import compare_fit, create_domain_router
from app.workbench.engine import build_checks
from app.workbench.models import Project
from app.workbench.module_fit import fit_preview
from app.workbench.proposals import build_proposal
from app.workbench.revisions import invalidate_connections
from app.workbench.store import WorkbenchStore


def sample():
    project = Project(references=[{'id': 'source', 'kind': 'note', 'name': 'Reference',
                                   'text': 'Explicit sample reference'}])
    return Project.model_validate({**project.model_dump(mode='json'), **cafe_candidate(project)['patch']})


def setup(tmp_path):
    store = WorkbenchStore(tmp_path)
    project = store.save(sample())
    app = FastAPI()
    app.include_router(create_domain_router(store))
    return store, project, TestClient(app), '/api/workbench/projects/' + project.id


def test_fit_does_not_invent_physical_scale():
    project = sample()
    initial = deepcopy(project.scale)
    result = fit_preview(project, 'sitting-support', 'seat_height_mm', 430)
    assert 'scale' not in result['patch']
    updated = Project.model_validate({**project.model_dump(mode='json'), **result['patch']})
    assert updated.scale == initial
    assert updated.modules[0].decisions['seat_height_mm'] == 'custom'


def test_same_method_preserves_choice_but_invalid_geometry_still_blocks():
    project = sample()
    for joint in project.joints:
        joint.confirmed = True
    data = project.model_dump(mode='json')
    data['parts'][0]['position_mm'][0] += 1000
    invalidate_connections(project, data)
    assert all(joint['confirmed'] for joint in data['joints'])
    assert any(item['severity'] == 'blocker' and item['code'] in {
        'joint_parts_separated', 'joint_holes_misaligned'} for item in build_checks(data))
    data['joints'][0]['kind'] = 'dowel'
    invalidate_connections(project, data)
    assert not data['joints'][0]['confirmed']


def test_baseline_is_immutable_and_profile_does_not_resize(tmp_path):
    store, project, client, url = setup(tmp_path)
    baseline = client.post(url + '/baseline', json={'expected_revision': 1}).json()
    assert baseline['baseline_revision'] == 1
    profile = client.post(url + '/profile', json={
        'expected_revision': baseline['revision'], 'module_id': 'sitting-support',
        'height_mm': 1800, 'sitting_height_mm': 1000, 'hip_width_mm': 550, 'posture': 'leaning'})
    assert profile.status_code == 200
    updated = profile.json()
    assert updated['parts'] == baseline['parts']
    assert updated['scale'] == baseline['scale']
    assert client.get('/api/workbench/profile').json()['hip_width_mm'] == 550
    assert client.post(url + '/baseline', json={
        'expected_revision': updated['revision'], 'source_revision': 2}).status_code == 409
    comparison = client.get(url + '/modules/sitting-support/comparison').json()
    assert all(item['suggested_value'] is None for item in comparison['items'])
    assert next(item for item in comparison['items'] if item['key'] == 'seat_depth_mm')['original_value'] == 215


def test_width_change_requires_explicit_redesign_and_does_not_commit_preview(tmp_path):
    store, project, client, url = setup(tmp_path)
    project = client.post(url + '/baseline', json={'expected_revision': 1}).json()
    edit = {'expected_revision': project['revision'], 'key': 'seat_width_mm', 'value': 655}
    conflict = client.post(url + '/modules/sitting-support/edit-preview', json=edit)
    assert conflict.status_code == 409
    assert conflict.json()['detail']['code'] == 'preservation_decision'
    preview = client.post(url + '/modules/sitting-support/edit-preview', json={**edit, 'allow_redesign': True})
    assert preview.status_code == 200
    assert preview.json()['patch']['design_intent'] == 'redesign'
    assert store.load(project['id']).model_dump(mode='json')['parts'] == project['parts']


def test_scale_anchor_must_match_an_actual_model_dimension(tmp_path):
    _, _, client, url = setup(tmp_path)
    assert client.post(url + '/scale-anchor', json={
        'expected_revision': 1, 'length_mm': 7777, 'note': 'Measured seat width'}).status_code == 422
    response = client.post(url + '/scale-anchor', json={
        'expected_revision': 1, 'length_mm': 400, 'note': 'Seat width measured from reference drawing'})
    assert response.status_code == 200
    assert response.json()['scale']['confirmed']


def test_agent_cannot_promote_inferred_preservation_to_verified():
    project = sample()
    proposal = build_proposal(project, 'Proposed limits', {'preservation': {
        'status': 'verified', 'features': ['Same chair'], 'source_ids': ['source']}})
    assert proposal['patch']['preservation']['status'] == 'inferred'


def test_suggestions_for_old_body_data_are_not_applied():
    project = sample()
    module = project.modules[0]
    module.anthropometry = {'stature_mm': 1800}
    module.suggestions = []
    from app.workbench.models import FitSuggestion
    module.suggestions.append(FitSuggestion(key='seat_height_mm', value=430,
        reason='Earlier user-specific suggestion', anthropometry={'stature_mm': 1700}))
    assert all(item['suggested_value'] is None for item in compare_fit(project, module, project)['items'])


def test_common_guard_rejects_unrelated_edit_after_a_height_decision(tmp_path):
    store, project, client, url = setup(tmp_path)
    response = client.post(url + '/baseline', json={'expected_revision': 1})
    project = Project.model_validate(response.json())
    fit = fit_preview(project, 'sitting-support', 'seat_height_mm', 430)
    project = store.change(project.id, project.revision, fit['patch'])
    changed = project.model_dump(mode='json')['parts']
    next(part for part in changed if part['kind'] == 'seat_board')['size_mm'][0] = 655
    import pytest
    with pytest.raises(ValueError, match='保型'):
        store.change(project.id, project.revision, {'parts': changed})


def test_material_change_does_not_require_shape_redesign(tmp_path):
    store, project, client, url = setup(tmp_path)
    project = Project.model_validate(client.post(url + '/baseline', json={'expected_revision': 1}).json())
    materials = project.model_dump(mode='json')['materials']
    next(iter(materials.values()))['name'] = 'User-selected ash board'
    result = store.change(project.id, project.revision, {'materials': materials})
    assert result.design_intent == 'restoration'


def test_restoring_accepted_revision_retains_baseline(tmp_path):
    store, project, client, url = setup(tmp_path)
    project = Project.model_validate(client.post(url + '/baseline', json={'expected_revision': 1}).json())
    proposal = client.post(url + '/modules/sitting-support/edit-preview', json={
        'expected_revision': project.revision, 'key': 'seat_width_mm', 'value': 470,
        'allow_redesign': True}).json()
    changed = store.change(project.id, project.revision, proposal['patch'])
    restored = store.restore(project.id, 1, changed.revision)
    assert restored.baseline_revision == 1
    assert restored.parts == project.parts
    assert restored.design_intent == 'restoration'


def test_ready_advice_survives_dimension_preview_without_early_design_mutation(tmp_path):
    from app.workbench.design_runs import DesignRuns

    store, _, client, url = setup(tmp_path)
    project = Project.model_validate(client.post(url + '/baseline', json={'expected_revision': 1}).json())
    before = project.model_dump(mode='json')
    modules = deepcopy(before['modules'])
    modules[0]['suggestions'] = [
        {'key': 'seat_height_mm', 'value': 430, 'reason': '坐姿反馈后提出较低座高预览',
         'source_ids': ['source'], 'anthropometry': modules[0]['anthropometry']},
        {'key': 'seat_width_mm', 'value': 440, 'reason': '另一个待用户取舍的座宽建议',
         'source_ids': ['source'], 'anthropometry': modules[0]['anthropometry']},
    ]
    runner = DesignRuns(store)
    run = runner.create(project.id, project.revision, 'modify', '只提出尺寸建议')
    runner.claim(project.id, run['id'], project.revision, 'advice-regression')
    checked = runner.preview(project.id, run['id'], project.revision,
                             'advice-regression', '尺寸建议', {'modules': modules})
    result = runner.finish(project.id, run['id'], project.revision,
                           'advice-regression', checked['proposal']['id'])
    assert result['result_kind'] == 'advice'
    assert store.load(project.id).model_dump(mode='json') == before

    comparison = client.get(url + '/modules/sitting-support/comparison').json()
    height = next(item for item in comparison['items'] if item['key'] == 'seat_height_mm')
    assert height['suggested_value'] == 430
    response = client.post(url + '/modules/sitting-support/edit-preview', json={
        'expected_revision': project.revision, 'key': 'seat_height_mm',
        'value': 430, 'decision': 'adopt'})
    assert response.status_code == 200
    proposal = response.json()
    assert proposal['base_revision'] == project.revision
    assert proposal['preservation_conflict'] is None
    proposed_module = proposal['patch']['modules'][0]
    assert proposed_module['suggestions'] == modules[0]['suggestions']
    assert proposed_module['anthropometry'] == before['modules'][0]['anthropometry']
    assert proposed_module['decisions']['seat_height_mm'] == 'adopt'
    assert proposed_module['target']['seat_height_mm'] == 430
    assert proposed_module['target']['seat_width_mm'] == before['modules'][0]['target']['seat_width_mm']
    assert 'scale' not in proposal['patch']
    assert 'preservation' not in proposal['patch']
    assert store.load(project.id).model_dump(mode='json') == before

    adopted = store.change(project.id, project.revision, proposal['patch'])
    assert adopted.modules[0].suggestions[1].value == 440
    assert adopted.scale == project.scale
    assert adopted.preservation == project.preservation
    assert runner.get(project.id, run['id'])['status'] == 'stale'
