"""Module intent must change manufacturing geometry, with revision-safe consent."""
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.workbench import api
from app.workbench.demo import cafe_candidate
from app.workbench.engine import _bounds, build_checks
from app.workbench.models import Project, ModuleConstraint
from app.workbench.module_fit import fit_preview
from app.workbench.store import WorkbenchStore


def sample():
    project = Project(name='Fit fixture', references=[{'id': 'sample-source', 'kind': 'note', 'name': 'Sample', 'text': 'Explicit CAFE chair sample'}])
    return Project.model_validate({**project.model_dump(mode='json'), **cafe_candidate(project)['patch']})


def test_four_steps_modify_actual_geometry_and_preserve_connection_checks():
    project = sample()
    original = project.model_dump(mode='json')
    for key, value in [('seat_height_mm', 361), ('seat_depth_mm', 309), ('seat_width_mm', 470), ('back_angle_deg', 24)]:
        result = fit_preview(project, 'sitting-support', key, value)
        project = Project.model_validate({**project.model_dump(mode='json'), **result['patch']})
        assert project.modules[0].target[key] == value
        assert not [c for c in result['checks'] if c['severity'] == 'blocker' and c['code'] not in {'scale_unconfirmed', 'joint_unconfirmed'}]
    parts = {p.id: p.model_dump(mode='json') for p in project.parts}
    assert parts['seat']['size_mm'][0] == 470
    assert parts['seat']['size_mm'][2] == 309
    assert _bounds(parts['seat'])[1][1] == pytest.approx(361)
    assert parts['back']['rotation_deg'][0] == -114
    for pid in ['back', 'side_left', 'side_right']:
        assert _bounds(parts[pid])[0][1] == pytest.approx(0, abs=.1)
    assert project.model_dump(mode='json')['scale'] == original['scale']
    assert not any('10°' in note for note in project.assumptions)
    assert any('24°' in note for note in project.assumptions)
    assert project.modules[0].status == 'target'
    assert original['parts'] != project.model_dump(mode='json')['parts']
    assert all(not joint.confirmed for joint in project.joints)


@pytest.mark.parametrize('angle', [0, 5, 15, 25])
def test_angle_rebuilds_paired_drilling_and_matching_hardware(angle):
    result = fit_preview(sample(), 'sitting-support', 'back_angle_deg', angle)
    assert result['patch']['parts']
    assert not [c for c in result['checks'] if c['severity'] == 'blocker' and c['code'] not in {'scale_unconfirmed', 'joint_unconfirmed'}]


def test_manufacturing_constraint_is_not_softened():
    project = sample()
    project.modules[0].notes = 'User manufacturing constraint'
    project.modules[0].constraints = [ModuleConstraint(key='seat_height_mm', operator='range',
        min_mm=380, max_mm=520, priority='required', label='加工者提供的最低支撑高度')]
    with pytest.raises(ValueError, match='此尺寸暂不能应用'):
        fit_preview(project, 'sitting-support', 'seat_height_mm', 361)


def test_unsupported_construction_and_unbuildable_values_fail_without_mutation():
    project = sample()
    before = project.model_dump(mode='json')
    with pytest.raises(ValueError):
        fit_preview(project, 'sitting-support', 'back_angle_deg', 50)
    with pytest.raises(ValueError):
        fit_preview(project, 'sitting-support', 'seat_width_mm', 100)
    assert project.model_dump(mode='json') == before


def test_preview_apply_and_joint_consent_are_revision_guarded(tmp_path, monkeypatch):
    store = WorkbenchStore(tmp_path)
    monkeypatch.setattr(api, 'workbench_store', store)
    project = sample()
    project.scale.confirmed = True  # Explicit target-scale consent precedes node consent.
    project = store.save(project)
    client = TestClient(app)
    url = '/api/workbench/projects/' + project.id
    fit_url = url + '/modules/sitting-support/'
    body = {'expected_revision': 1, 'key': 'seat_height_mm', 'value': 361}
    response = client.post(fit_url + 'fit-preview', json=body)
    assert response.status_code == 200, response.text
    assert store.load(project.id).revision == 1
    applied = client.post(fit_url + 'fit-apply', json=body)
    assert applied.status_code == 200, applied.text
    assert applied.json()['revision'] == 2
    assert client.post(fit_url + 'fit-apply', json=body).status_code == 409
    for key, value in [('seat_depth_mm', 309), ('seat_width_mm', 470), ('back_angle_deg', 24)]:
        current = store.load(project.id)
        response = client.post(fit_url + 'fit-apply', json={'expected_revision': current.revision, 'key': key, 'value': value})
        assert response.status_code == 200, response.text
    current = store.load(project.id)
    joint = current.joints[0]
    accepted = client.post(url + '/joints/' + joint.id + '/accept', json={'expected_revision': current.revision})
    assert accepted.status_code == 200, accepted.text
    assert next(j for j in accepted.json()['joints'] if j['id'] == joint.id)['confirmed']
    assert client.post(url + '/joints/' + joint.id + '/accept', json={'expected_revision': current.revision}).status_code == 409
    current = store.load(project.id)
    broken = deepcopy(current.model_dump(mode='json')['parts'])
    part = next(p for p in broken if p['id'] == joint.part_ids[0])
    part['position_mm'][0] += 2000
    current = store.change(project.id, current.revision, {'parts': broken})
    rejected = client.post(url + '/joints/' + joint.id + '/accept', json={'expected_revision': current.revision})
    assert rejected.status_code == 422
    assert store.load(project.id).revision == current.revision
