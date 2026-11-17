"""Local proposal imports obey the same boundary as model suggestions."""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.workbench import api
from app.workbench.store import WorkbenchStore

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "workbench_store", WorkbenchStore(tmp_path))
    return TestClient(app)

def start(client):
    project = client.post("/api/workbench/projects", json={"name": "Local import"}).json()
    return project, "/api/workbench/projects/" + project["id"]

def test_import_preview_does_not_mutate_project_and_accept_creates_draft(client):
    project, url = start(client)
    result = client.post(url + "/proposal/import", json={"expected_revision": 1,
        "summary": "Review new name", "patch": {"name": "Imported"}})
    assert result.status_code == 200
    proposal = result.json()
    assert proposal["status"] == "ready"
    assert proposal["source"] == "local_import"
    assert proposal["checks"]
    assert "not_checked" in proposal["coverage"]
    assert client.get(url).json() == project
    accepted = client.post(url + "/proposal/accept", json={"expected_revision": 1,
        "proposal_id": proposal["id"]}).json()
    assert accepted["revision"] == 2 and accepted["name"] == "Imported"
    assert accepted["confirmed_revision"] is None

def test_import_cannot_assert_scale_or_connection_confirmation(client):
    _, url = start(client)
    result = client.post(url + "/proposal/import", json={"expected_revision": 1,
        "summary": "Local design", "patch": {
            "scale": {"kind": "target", "confirmed": True, "length_mm": 450},
            "joints": [{"id": "join", "kind": "screw", "part_ids": ["a", "b"], "confirmed": True}]}})
    assert result.status_code == 200
    patch = result.json()["patch"]
    assert patch["scale"]["confirmed"] is False
    assert patch["joints"][0]["confirmed"] is False

@pytest.mark.parametrize("patch", [
    {"confirmed_revision": 1}, {"references": []}, {"parts": None},
    {"joints": [None]}, {"scale": "invalid"},
    {"evidence": [{"statement": "Missing reference", "source_ids": ["not-present"]}]},
])
def test_invalid_import_returns_422_and_preserves_project(client, patch):
    project, url = start(client)
    result = client.post(url + "/proposal/import", json={"expected_revision": 1,
        "summary": "Invalid", "patch": patch})
    assert result.status_code == 422
    assert client.get(url).json() == project
    assert client.get(url + "/proposal").status_code == 404

def test_import_rejects_stale_version_and_cannot_replace_previous_proposal(client):
    _, url = start(client)
    proposal = client.post(url + "/proposal/import", json={"expected_revision": 1,
        "summary": "Valid proposal", "patch": {}}).json()
    client.put(url, json={"expected_revision": 1, "patch": {"name": "New version"}})
    result = client.post(url + "/proposal/import", json={"expected_revision": 1,
        "summary": "Stale", "patch": {}})
    assert result.status_code == 409
    assert client.get(url + "/proposal").json()["id"] == proposal["id"]

def test_import_rejects_oversize_and_invalid_envelope(client):
    _, url = start(client)
    assert client.post(url + "/proposal/import", content=b" " * (2 * 1024 * 1024 + 1)).status_code == 413
    assert client.post(url + "/proposal/import", content=b"{broken").status_code == 422
    assert client.post(url + "/proposal/import", json={"expected_revision": True,
        "summary": "Invalid version", "patch": {}}).status_code == 422
    assert client.get(url).json()["revision"] == 1


def test_preview_matches_acceptance_invalidation_for_geometry_change(client):
    from app.workbench.models import Project
    project = Project.model_validate({
        "name": "Existing connections",
        "materials": {"wood": {"name": "Wood", "kind": "solid_wood", "grain_axis": "x"}},
        "parts": [
            {"id": "a", "name": "A", "material_id": "wood", "size_mm": [100, 20, 50]},
            {"id": "b", "name": "B", "material_id": "wood", "size_mm": [100, 20, 50]},
        ],
        "joints": [{"id": "join", "kind": "screw", "part_ids": ["a", "b"], "confirmed": True}],
    })
    api.workbench_store.save(project)
    url = "/api/workbench/projects/" + project.id
    parts = project.model_dump(mode="json")["parts"]
    parts[0]["size_mm"][0] = 110
    proposal = client.post(url + "/proposal/import", json={"expected_revision": 1,
        "summary": "Resize", "patch": {"parts": parts}}).json()
    assert any(check["code"] == "joint_unconfirmed" for check in proposal["checks"])
    accepted = client.post(url + "/proposal/accept", json={"expected_revision": 1,
        "proposal_id": proposal["id"]}).json()
    assert accepted["joints"][0]["confirmed"] is False
    assert client.get(url + "/checks").json()["checks"] == proposal["checks"]
