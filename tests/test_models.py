from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.domain.models import DesignManifest, MaterialSpec, PartSpec
from app.main import app
from app.storage.fs import ProjectStore


def test_manifest_defaults_are_editable():
    manifest = DesignManifest(name="AA Stool")
    manifest.materials["main"] = MaterialSpec(kind="solid_wood", name="Pine", stock_thickness_mm=25)
    manifest.parts.append(
        PartSpec(id="seat", name="Seat", kind="seat_board", dimensions_mm={"width": 360, "depth": 380})
    )

    assert manifest.version == 1
    assert manifest.materials["main"].name == "Pine"
    assert manifest.parts[0].dimensions_mm["width"] == 360


def test_manifest_round_trips_with_project_id():
    project_id = uuid4()
    manifest = DesignManifest(project_id=project_id)

    restored = DesignManifest.model_validate_json(manifest.model_dump_json())

    assert restored.project_id == project_id


def test_reference_url_and_file_are_recorded(tmp_path: Path):
    client = TestClient(app)
    from app.main import store
    original_root = store.root
    store.root = tmp_path
    try:
        created = client.post("/api/projects", json={"name": "Reference test"})
        assert created.status_code == 200
        project_id = created.json()["project_id"]

        source = client.post(
            f"/api/projects/{project_id}/references",
            json={"kind": "url", "uri": "https://example.com/chair"},
        )
        assert source.status_code == 200
        assert source.json()["version"] == 2

        image = client.post(
            f"/api/projects/{project_id}/reference-file?filename=chair.jpg",
            content=b"fake-image",
            headers={"content-type": "image/jpeg"},
        )
        assert image.status_code == 200
        assert image.json()["reference_sources"][-1]["kind"] == "image"
        assert (tmp_path / str(project_id) / "references" / "chair.jpg").read_bytes() == b"fake-image"
    finally:
        store.root = original_root
