"""Workbench API invariants. These tests do not call external AI."""
from pathlib import Path
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.workbench import api as workbench
from app.workbench.models import Project
from app.workbench.store import WorkbenchStore

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(workbench, "workbench_store", WorkbenchStore(tmp_path))
    return TestClient(app)

def create(client):
    response = client.post("/api/workbench/projects", json={"name": "Joinery project"})
    assert response.status_code == 200
    return response.json()

def endpoint(project):
    return "/api/workbench/projects/" + project["id"]

def test_revision_conflict_cannot_overwrite_current_project(client):
    project = create(client)
    url = endpoint(project)
    first = client.put(url, json={"expected_revision": 1, "patch": {"name": "Accepted"}})
    assert first.status_code == 200
    stale = client.put(url, json={"expected_revision": 1, "patch": {"name": "Stale"}})
    assert stale.status_code == 409
    assert client.get(url).json()["name"] == "Accepted"

def test_versions_are_immutable_and_restore_creates_new_draft(client):
    project = create(client)
    url = endpoint(project)
    client.put(url, json={"expected_revision": 1, "patch": {"name": "Second"}})
    restored = client.post(url + "/restore/1", json={"expected_revision": 2})
    assert restored.status_code == 200
    assert restored.json()["revision"] == 3
    assert restored.json()["name"] == "Joinery project"
    assert restored.json()["confirmed_revision"] is None
    versions = client.get(url + "/versions").json()
    assert [v["revision"] for v in versions] == [3, 2, 1]
    assert versions[1]["name"] == "Second"

def test_patch_cannot_self_confirm_or_publish_incomplete_project(client):
    project = create(client)
    url = endpoint(project)
    assert client.put(url, json={"expected_revision": 1, "patch": {"confirmed_revision": 1}}).status_code == 422
    assert client.post(url + "/confirm", json={"expected_revision": 1, "acknowledged_limits": True}).status_code == 409
    assert client.get(url + "/package").json()["status"] == "draft"
    assert client.get(url + "/package/download?revision=1").status_code == 409

def test_old_ai_proposal_is_rejected_after_any_design_change(client):
    project = create(client)
    url = endpoint(project)
    proposal = {"id": str(uuid4()), "base_revision": 1, "status": "ready",
                "summary": "Old proposal", "patch": {"name": "AI old"}}
    workbench.workbench_store.save_proposal(project["id"], proposal)
    client.put(url, json={"expected_revision": 1, "patch": {"name": "User new"}})
    response = client.post(url + "/proposal/accept", json={"expected_revision": 2, "proposal_id": proposal["id"]})
    assert response.status_code == 409
    assert client.get(url).json()["name"] == "User new"

def test_missing_ai_configuration_does_not_create_fake_geometry(client, monkeypatch):
    for name in ("CREATE_JUNIOR_AI_BASE_URL", "CREATE_JUNIOR_AI_API_KEY", "CREATE_JUNIOR_AI_MODEL"):
        monkeypatch.delenv(name, raising=False)
    project = create(client)
    response = client.post(endpoint(project) + "/analyze")
    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert client.get(endpoint(project)).json()["parts"] == []

def test_inventory_is_optional_and_not_consumed_by_package_preview(client):
    project = create(client)
    inventory = [{"id": "stock", "name": "Wood", "quantity": 3}]
    client.put("/api/workbench/context", json={"expected_revision": 1, "inventory": inventory})
    client.get(endpoint(project) + "/package")
    assert client.get("/api/workbench/context").json()["inventory"] == inventory

def test_upload_rejects_unrecognized_image_without_mutation(client):
    project = create(client)
    response = client.post(endpoint(project) + "/references?filename=bad.png", content=b"not an image",
                           headers={"Content-Type": "image/png"})
    assert response.status_code == 415
    assert client.get(endpoint(project)).json()["revision"] == 1

def test_ui_and_local_dependencies_are_served(client):
    page = client.get("/")
    assert "下一步" in page.text
    assert "viewport.js" in client.get("/static/app.js").text
    assert client.get("/static/vendor/three/three.module.js").status_code == 200



def test_invalid_design_patch_is_validation_error_not_server_error(client):
    project = create(client)
    for patch in ({"parts": None}, {"parts": [{}]}, {"materials": None}):
        response = client.put(endpoint(project), json={"expected_revision": 1, "patch": patch})
        assert response.status_code == 422
    assert client.get(endpoint(project)).json()["revision"] == 1

def test_context_conflict_preserves_first_inventory_update(client):
    assert client.put("/api/workbench/context", json={"expected_revision": 1, "inventory": [{"id": "a"}]}).status_code == 200
    assert client.put("/api/workbench/context", json={"expected_revision": 1, "inventory": [{"id": "b"}]}).status_code == 409
    assert client.get("/api/workbench/context").json()["inventory"] == [{"id": "a"}]

def test_complete_snapshot_recovers_interrupted_current_write(tmp_path, monkeypatch):
    store = WorkbenchStore(tmp_path)
    project = store.save(Project(name="Original"))
    original_write = store.atomic_json
    def fail_current(path, value):
        if path.name == "project.json":
            raise OSError("simulated interruption")
        original_write(path, value)
    monkeypatch.setattr(store, "atomic_json", fail_current)
    with pytest.raises(OSError):
        store.change(project.id, 1, {"name": "Committed snapshot"})
    monkeypatch.setattr(store, "atomic_json", original_write)
    recovered = store.load(project.id)
    assert recovered.revision == 2
    assert recovered.name == "Committed snapshot"
    assert store.change(project.id, 2, {"name": "Continue"}).revision == 3

def test_download_rejects_a_different_version_from_reviewed(client):
    project = create(client)
    client.put(endpoint(project), json={"expected_revision": 1, "patch": {"name": "New"}})
    response = client.get(endpoint(project) + "/package/download?revision=1")
    assert response.status_code == 409
    assert "设计已变化" in response.json()["detail"]
