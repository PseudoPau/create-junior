"""Preparation uses existing context and explicit user acceptance; no model calls."""
from pathlib import Path
import json
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.workbench import api as workbench
from app.workbench.store import WorkbenchStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(workbench, "workbench_store", WorkbenchStore(tmp_path))
    return TestClient(app)


def create(client):
    return client.post("/api/workbench/projects", json={"name": "Preparation"}).json()


def url(project):
    return "/api/workbench/projects/" + project["id"]


def design_patch():
    return {
        "materials": {"wood": {"name": "Reference timber", "kind": "solid_wood", "grain_axis": "x"}},
        "parts": [
            {"id": "a", "name": "A", "material_id": "wood", "size_mm": [100, 20, 100]},
            {"id": "b", "name": "B", "material_id": "wood", "size_mm": [100, 20, 100], "position_mm": [0, -20, 0]},
        ],
        "joints": [{"id": "ab", "kind": "screw", "part_ids": ["a", "b"],
                    "assembly_note": "Joint design remains incomplete", "confirmed": True}],
    }


def test_preparation_only_asks_missing_user_conditions(client):
    p = create(client)
    data = client.get(url(p) + "/preparation").json()
    assert [q["key"] for q in data["missing_questions"]] == ["fabrication_mode", "load_kg", "environment"]
    assert data["request"] is None
    assert data["package_preview"]["status"] == "draft"
    client.put(url(p), json={"expected_revision": 1, "patch": {
        "fabrication_mode": "shop", "requirements": {"load_kg": 90, "environment": "indoor", "notes": "Keep the original silhouette"}}})
    data = client.get(url(p) + "/preparation").json()
    assert data["missing_questions"] == []
    assert data["conditions"]["requirements"]["notes"] == "Keep the original silhouette"
    assert client.get(url(p)).json()["revision"] == 2


def test_request_snapshots_conditions_and_original_design_without_mutation(client):
    p = create(client)
    client.put(url(p), json={"expected_revision": 1, "patch": design_patch()})
    client.put(url(p), json={"expected_revision": 2, "patch": {"name": "Adjusted"}})
    before = client.get(url(p)).json()
    response = client.post(url(p) + "/preparation/request", json={"expected_revision": 3, "text": "Prefer simple machining"})
    assert response.status_code == 200
    request = response.json()
    assert request["status"] == "pending"
    assert request["project"] == before
    assert request["original_design"]["revision"] == 2
    assert request["text"] == "Prefer simple machining"
    assert client.get(url(p)).json() == before
    path = workbench.workbench_store.directory(p["id"]) / "preparation" / "requests" / (request["id"] + ".json")
    assert json.loads(path.read_text())["id"] == request["id"]


def test_request_revision_conflict_and_staleness(client):
    p = create(client)
    assert client.post(url(p) + "/preparation/request", json={"expected_revision": 2}).status_code == 409
    request = client.post(url(p) + "/preparation/request", json={"expected_revision": 1}).json()
    client.put(url(p), json={"expected_revision": 1, "patch": {"name": "Changed"}})
    data = client.get(url(p) + "/preparation").json()
    assert data["request"]["id"] == request["id"]
    assert data["request"]["status"] == "stale"


def test_manufacturing_acceptance_records_consent_but_keeps_real_blockers(client):
    p = create(client)
    request = client.post(url(p) + "/preparation/request", json={"expected_revision": 1}).json()
    proposal = client.post(url(p) + "/proposal/import", json={"expected_revision": 1,
        "purpose": "manufacturing", "summary": "Review this manufacturing plan", "patch": design_patch()}).json()
    assert proposal["purpose"] == "manufacturing"
    assert proposal["package_preview"]["status"] == "draft"
    assert proposal["patch"]["joints"][0]["confirmed"] is False
    assert client.get(url(p) + "/preparation").json()["request"]["status"] == "ready"
    response = client.post(url(p) + "/proposal/accept", json={"expected_revision": 1,
        "proposal_id": proposal["id"], "accept_connections": True})
    assert response.status_code == 200
    current = response.json()
    assert current["joints"][0]["confirmed"] is True
    assert current["confirmed_revision"] is None
    completed = client.get(url(p) + "/preparation").json()["request"]
    assert completed["status"] == "completed"
    assert completed["result_revision"] == current["revision"]
    checks = client.get(url(p) + "/checks").json()["checks"]
    codes = {item["code"] for item in checks}
    assert "joint_unconfirmed" not in codes
    assert "joint_features_missing" in codes
    assert "hardware_missing" in codes
    assert client.post(url(p) + "/confirm", json={"expected_revision": 2, "acknowledged_limits": True}).status_code == 409
    changed = current["parts"]
    changed[0]["size_mm"][0] = 120
    updated = client.put(url(p), json={"expected_revision": 2, "patch": {"parts": changed}}).json()
    assert updated["joints"][0]["confirmed"] is False


def test_design_candidate_cannot_claim_manufacturing_acceptance(client):
    p = create(client)
    proposal = client.post(url(p) + "/proposal/import", json={"expected_revision": 1,
        "summary": "Ordinary design", "patch": design_patch()}).json()
    response = client.post(url(p) + "/proposal/accept", json={"expected_revision": 1,
        "proposal_id": proposal["id"], "accept_connections": True})
    assert response.status_code == 422
    assert client.get(url(p)).json()["revision"] == 1


def test_preexisting_proposal_does_not_fulfil_a_new_request(client):
    p = create(client)
    client.post(url(p) + "/proposal/import", json={"expected_revision": 1,
        "purpose": "manufacturing", "summary": "Old plan", "patch": design_patch()})
    client.post(url(p) + "/preparation/request", json={"expected_revision": 1, "text": "Try another option"})
    assert client.get(url(p) + "/preparation").json()["request"]["status"] == "pending"


@pytest.mark.parametrize("height", [166, 40, 350])
def test_stored_height_does_not_interrupt_manufacturing_preparation(client, height):
    p = create(client)
    client.put(url(p), json={"expected_revision": 1, "patch": {"requirements": {"body_height_mm": height}}})
    questions = client.get(url(p) + "/preparation").json()["missing_questions"]
    assert "body_height_mm" not in {question["key"] for question in questions}
    assert client.get(url(p)).json()["requirements"]["body_height_mm"] == height


def test_blank_request_retains_prior_free_text_as_unresolved_input(client):
    p = create(client)
    first = client.post(url(p) + "/preparation/request", json={"expected_revision": 1, "text": "Use existing timber"}).json()
    second = client.post(url(p) + "/preparation/request", json={"expected_revision": 1}).json()
    assert second["text"] == ""
    assert second["user_instructions"] == first["user_instructions"]
    assert second["user_instructions"][0]["text"] == "Use existing timber"
    assert client.get(url(p)).json()["requirements"]["notes"] == ""
