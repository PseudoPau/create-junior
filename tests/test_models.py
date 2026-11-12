from uuid import uuid4

from app.domain.models import DesignManifest, MaterialSpec, PartSpec


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
