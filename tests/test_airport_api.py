from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app, store


def test_airport_status_is_non_blocking_when_create_is_not_running():
    client = TestClient(app)
    response = client.get("/api/airport/status")

    assert response.status_code == 200
    assert response.json()["status"] in {"ready", "unavailable"}


def test_airport_commit_keeps_local_outputs_available_when_unavailable(tmp_path: Path, monkeypatch):
    client = TestClient(app)
    original_root = store.root
    store.root = tmp_path
    try:
        created = client.post("/api/projects", json={"name": "Offline project"})
        project_id = created.json()["project_id"]
        response = client.post(f"/api/projects/{project_id}/airport/commit")

        assert response.status_code == 409
        package = client.get(f"/api/projects/{project_id}/fabrication-package")
        assert package.status_code == 200
    finally:
        store.root = original_root
