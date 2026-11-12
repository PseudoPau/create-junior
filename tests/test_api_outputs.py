from pathlib import Path
from zipfile import ZipFile
from io import BytesIO

from fastapi.testclient import TestClient

from app.main import app, store


def test_project_outputs_include_fabrication_and_load_estimate(tmp_path: Path):
    client = TestClient(app)
    original_root = store.root
    store.root = tmp_path
    try:
        created = client.post("/api/projects", json={
            "name": "AA Stool",
            "user_profile": {"seat_height_mm": 420, "seat_width_mm": 360, "seat_depth_mm": 380, "estimated_load_kg": 80},
            "materials": {"main": {"kind": "solid_wood", "name": "pine", "stock_thickness_mm": 25}},
            "parts": [{"id": "seat", "name": "Seat", "kind": "seat_board", "dimensions_mm": {"width": 360, "height": 380}}],
        })
        project_id = created.json()["project_id"]

        package = client.get(f"/api/projects/{project_id}/fabrication-package")
        estimate = client.get(f"/api/projects/{project_id}/load-estimate")

        assert package.status_code == 200
        assert package.json()["cut_list"][0]["part_id"] == "seat"
        assert estimate.status_code == 200
        assert estimate.json()["material_name"]

        download = client.get(f"/api/projects/{project_id}/fabrication-package/download")
        assert download.status_code == 200
        with ZipFile(BytesIO(download.content)) as archive:
            assert {"manifest.json", "fabrication-package.json", "README.txt"}.issubset(archive.namelist())
    finally:
        store.root = original_root
