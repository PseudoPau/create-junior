"""Canonical angles use the existing candidate transaction, never naked rotation."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.workbench.demo import cafe_candidate
from app.workbench.domain_flow import compare_fit, create_domain_router
from app.workbench.models import FitSuggestion, Preservation, Project
from app.workbench.store import WorkbenchStore


def setup(tmp_path, tilt=0):
    source = Project(references=[{'id': 'source', 'kind': 'note', 'name': 'Reference',
                                  'text': 'Explicit chair reference'}])
    project = Project.model_validate({**source.model_dump(mode='json'),
                                     **cafe_candidate(source)['patch']})
    if tilt:
        next(part for part in project.parts if part.id == 'seat').rotation_deg = (-tilt, 0, 0)
    store = WorkbenchStore(tmp_path)
    project = store.save(project)
    app = FastAPI()
    app.include_router(create_domain_router(store))
    url = '/api/workbench/projects/' + project.id + '/modules/sitting-support/edit-preview'
    return store, project, TestClient(app), url


@pytest.mark.parametrize('key,value,current', [
    ('seat_back_angle_deg', 105, 100), ('back_angle_deg', 15, 10)])
def test_canonical_and_legacy_angles_share_compiler_and_preserve_response_units(tmp_path, key, value, current):
    store, project, client, url = setup(tmp_path)
    before = project.model_dump(mode='json')
    response = client.post(url, json={'expected_revision': project.revision, 'key': key,
        'value': value, 'decision': 'adopt', 'allow_redesign': True})
    assert response.status_code == 200, response.text
    proposal = response.json()
    assert proposal['edit'] == {'module_id': 'sitting-support', 'key': key,
                                'value': value, 'current_value': current}
    assert proposal['source'] == 'dimension_edit'
    assert proposal['base_revision'] == project.revision
    assert next(part for part in proposal['patch']['parts'] if part['id'] == 'back')['rotation_deg'][0] == -105
    module = next(item for item in proposal['patch']['modules'] if item['id'] == 'sitting-support')
    assert module['target']['back_angle_deg'] == 15
    assert module['decisions']['back_angle_deg'] == 'adopt'
    assert 'seat_back_angle_deg' not in module['decisions']
    assert store.load(project.id).model_dump(mode='json') == before
    assert store.proposal(project.id, proposal['id'])['edit'] == proposal['edit']


def test_canonical_preservation_conflict_stays_in_canonical_units(tmp_path):
    store, project, client, url = setup(tmp_path)
    response = client.post(url, json={'expected_revision': project.revision,
        'key': 'seat_back_angle_deg', 'value': 105})
    assert response.status_code == 409
    detail = response.json()['detail']
    assert detail['code'] == 'preservation_decision'
    assert detail['key'] == 'seat_back_angle_deg'
    assert detail['original_value'] == 100
    assert detail['requested_value'] == 105
    assert not list((store.directory(project.id) / 'proposals').glob('*.json'))


@pytest.mark.parametrize('tilt,key,value', [
    (0, 'seat_tilt_deg', 5), (0, 'seat_tilt_deg', -5),
    (5, 'seat_back_angle_deg', 105), (5, 'seat_height_mm', 430),
    (5, 'seat_width_mm', 420), (5, 'seat_depth_mm', 250)])
def test_unsupported_edit_requires_agent_without_candidate_or_model_mutation(tmp_path, tilt, key, value):
    store, project, client, url = setup(tmp_path, tilt=tilt)
    before = project.model_dump(mode='json')
    response = client.post(url, json={'expected_revision': project.revision,
        'key': key, 'value': value, 'allow_redesign': True})
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'agent_required'
    assert response.json()['detail']['key'] == key
    assert response.json()['detail']['requested_value'] == value
    assert store.load(project.id).model_dump(mode='json') == before
    assert not list((store.directory(project.id) / 'proposals').glob('*.json'))


def test_revision_guard_precedes_unsupported_compiler_response(tmp_path):
    _, project, client, url = setup(tmp_path)
    response = client.post(url, json={'expected_revision': project.revision + 1,
        'key': 'seat_tilt_deg', 'value': -5})
    assert response.status_code == 409


@pytest.mark.parametrize('key,value', [('seat_width_mm', -1), ('seat_tilt_deg', 91),
                                     ('seat_back_angle_deg', 181), ('unknown', 1)])
def test_request_bounds_remain_explicit(tmp_path, key, value):
    _, project, client, url = setup(tmp_path)
    response = client.post(url, json={'expected_revision': project.revision,
                                     'key': key, 'value': value})
    assert response.status_code == 422


def advice(key, value, body=None):
    return FitSuggestion(key=key, value=value, reason='结合当前参考与身体数据提出',
                         anthropometry=body or {})


def test_comparison_query_defaults_to_legacy_but_canonical_keeps_five_dimensions(tmp_path):
    _, project, client, edit_url = setup(tmp_path)
    url = edit_url.replace('/edit-preview', '/comparison')
    old = client.get(url).json()['items']
    assert [item['key'] for item in old] == ['seat_height_mm', 'seat_depth_mm', 'seat_width_mm', 'back_angle_deg']
    response = client.get(url, params={'canonical': True})
    assert response.status_code == 200
    items = response.json()['items']
    assert [item['key'] for item in items] == ['seat_height_mm', 'seat_width_mm', 'seat_depth_mm', 'seat_tilt_deg', 'seat_back_angle_deg']
    assert [item['current_value'] for item in items] == [450, 400, 215, 0, 100]
    assert items[3]['capability'] == 'agent_required'
    assert items[4]['capability'] == 'local_compiler'


@pytest.mark.parametrize('suggestion_key,suggestion_value', [('back_angle_deg', 15), ('seat_back_angle_deg', 105)])
def test_comparison_uses_shared_preservation_and_compiler_in_correct_angle_units(tmp_path, suggestion_key, suggestion_value):
    _, project, _, _ = setup(tmp_path)
    project.preservation = Preservation(status='verified', limits=[
        {'key': 'back_angle_deg', 'min_mm': 5, 'max_mm': 20}])
    module = project.modules[0]
    module.suggestions = [advice(suggestion_key, suggestion_value, module.anthropometry),
                          advice('seat_tilt_deg', -5, module.anthropometry)]
    items = {item['key']: item for item in compare_fit(project, module, project, canonical=True)['items']}
    back = items['seat_back_angle_deg']
    assert back['original_value'] == back['current_value'] == 100
    assert back['suggested_value'] == 105
    assert back['allowed_range'] == {'min': 95, 'max': 110}
    assert back['status'] == 'suggested'
    assert back['editable']
    tilt = items['seat_tilt_deg']
    assert tilt['suggested_value'] == -5
    assert tilt['status'] == 'conflict'
    assert tilt['capability'] == 'agent_required'
    assert not tilt['editable']


def test_tilted_seat_does_not_convert_legacy_back_advice_or_claim_local_edit(tmp_path):
    _, project, _, _ = setup(tmp_path, tilt=5)
    module = project.modules[0]
    module.suggestions = [advice('back_angle_deg', 15, module.anthropometry)]
    item = compare_fit(project, module, None, canonical=True)['items'][-1]
    assert item['current_value'] == 95
    assert item['suggested_value'] is None
    assert item['status'] == 'unknown'
    assert '不能视为座背夹角' in item['reason']
    module.suggestions = [advice('seat_back_angle_deg', 105, module.anthropometry)]
    item = compare_fit(project, module, None, canonical=True)['items'][-1]
    assert item['suggested_value'] == 105
    assert item['capability'] == 'agent_required'
    assert not item['editable']
    assert item['status'] == 'conflict'


def test_canonical_advice_matches_body_and_prefers_explicit_included_angle(tmp_path):
    _, project, _, _ = setup(tmp_path)
    module = project.modules[0]
    module.anthropometry = {'stature_mm': 1800}
    module.suggestions = [advice('seat_tilt_deg', 5, {'stature_mm': 1700}),
        advice('back_angle_deg', 15, module.anthropometry),
        advice('seat_back_angle_deg', 108, module.anthropometry)]
    items = compare_fit(project, module, None, canonical=True)['items']
    assert items[3]['suggested_value'] is None
    assert items[4]['suggested_value'] == 108
