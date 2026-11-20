from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.workbench.demo import cafe_candidate
from app.workbench.models import Project
from app.workbench.review_api import create_review_router
from app.workbench.review import review_projection
from app.workbench.store import WorkbenchStore


def setup(tmp_path):
    source = Project(references=[{'id': 'ref', 'name': 'sample', 'kind': 'note', 'text': 'Explicit sample'}])
    project = Project.model_validate({**source.model_dump(mode='json'), **cafe_candidate(source)['patch']})
    project.scale.confirmed = True
    store = WorkbenchStore(tmp_path); store.save(project)
    app = FastAPI(); app.include_router(create_review_router(store))
    return store, project, TestClient(app)


def request_for(project, part_id):
    group = next(g for g in review_projection(project)['board_groups'] if part_id in g['part_ids'])
    body = {key: value for key, value in group['dimensions'].items() if key != 'axes'}
    body.update(expected_revision=project.revision, fingerprint=group['fingerprint'])
    return group, body, f'/api/workbench/projects/{project.id}/review/boards/{group["id"]}/edit-preview'


def test_symmetric_side_height_preview_changes_group_and_connections_atomically(tmp_path):
    store, project, client = setup(tmp_path)
    group, body, url = request_for(project, 'side_left')
    body['length_mm'] = 406
    before = project.model_dump(mode='json')
    response = client.post(url, json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['edit']['part_ids'] == ['side_left', 'side_right']
    parts = {part['id']: part for part in result['patch']['parts']}
    assert parts['side_left']['size_mm'][2] == parts['side_right']['size_mm'][2] == 406
    assert parts['seat']['position_mm'][1] + parts['seat']['size_mm'][1]/2 == 430
    assert store.load(project.id).model_dump(mode='json') == before
    assert not any(c['severity'] == 'blocker' and c['code'] in ('joint_holes_misaligned', 'joint_parts_separated') for c in result['checks'])


def test_board_thickness_needs_linked_agent_plan_without_silent_mutation(tmp_path):
    store, project, client = setup(tmp_path)
    _, body, url = request_for(project, 'seat'); body['thickness_mm'] = 28
    response = client.post(url, json=body)
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'agent_required'
    assert store.load(project.id).revision == project.revision
    assert not list((store.directory(project.id)/'proposals').glob('*.json'))


def test_stale_board_fingerprint_cannot_preview_different_geometry(tmp_path):
    store, project, client = setup(tmp_path)
    _, body, url = request_for(project, 'seat'); body['fingerprint'] = 'old-content'
    assert client.post(url, json=body).status_code == 409
    assert store.load(project.id).revision == project.revision
