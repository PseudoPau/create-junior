from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app, store


def test_structure_proposal_persists_parts_and_candidate_joinery(tmp_path: Path):
    client = TestClient(app)
    original_root = store.root
    store.root = tmp_path
    try:
        created = client.post(
            "/api/projects",
            json={
                "name": "AA Stool",
                "user_profile": {"seat_height_mm": 420, "seat_width_mm": 360, "seat_depth_mm": 380},
                "materials": {"main": {"kind": "solid_wood", "name": "pine", "stock_thickness_mm": 25}},
            },
        )
        project_id = created.json()["project_id"]
        proposal = client.post(f"/api/projects/{project_id}/proposal")

        assert proposal.status_code == 200
        assert [part["id"] for part in proposal.json()["parts"]] == ["seat", "side_left", "side_right"]
        assert all(joint["status"] == "candidate" for joint in proposal.json()["joinery"])
    finally:
        store.root = original_root
