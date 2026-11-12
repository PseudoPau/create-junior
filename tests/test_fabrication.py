from app.domain.models import DesignManifest, MaterialSpec, PartSpec, UserProfile
from app.fabrication.package import build_fabrication_package


def test_fabrication_package_contains_drawings_and_assembly_steps():
    manifest = DesignManifest(
        name="AA Stool",
        user_profile=UserProfile(seat_height_mm=420, seat_width_mm=360, seat_depth_mm=380),
        materials={"main": MaterialSpec(kind="solid_wood", stock_thickness_mm=25)},
        parts=[
            PartSpec(id="seat", name="Seat", kind="seat_board", dimensions_mm={"width": 360, "depth": 380, "height": 25}, material_ref="main", grain_direction="length"),
        ],
    )

    package = build_fabrication_package(manifest)

    assert package.manifest_version == 1
    assert package.status == "ready"
    assert package.cut_list[0].dimensions_mm["width"] == 360
    assert package.drawings[0].status == "ready"
    assert "<svg" in package.drawings[0].svg
    assert len(package.assembly_steps) == 3


def test_incomplete_part_is_visible_in_package():
    manifest = DesignManifest(parts=[PartSpec(id="seat", name="Seat", kind="seat_board")])

    package = build_fabrication_package(manifest)

    assert package.status == "incomplete"
    assert package.drawings[0].missing == ["width", "height"]
    assert package.validation
