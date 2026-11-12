from app.domain.models import DesignManifest, JoinerySpec, MaterialSpec, PartSpec, UserProfile
from app.domain.validation import validate_manifest


def test_missing_design_inputs_are_explicit_unknowns():
    issues = validate_manifest(DesignManifest())

    assert {issue.code for issue in issues} >= {"missing_dimension", "missing_material"}
    assert all(issue.severity == "unknown" for issue in issues if issue.code.startswith("missing_"))


def test_confirmed_basic_design_passes_without_strength_claim():
    manifest = DesignManifest(
        user_profile=UserProfile(seat_height_mm=420, seat_width_mm=360, seat_depth_mm=380),
        materials={"main": MaterialSpec(kind="solid_wood", stock_thickness_mm=25)},
        parts=[
            PartSpec(id="left", name="Left", kind="side_panel", dimensions_mm={"height": 395, "thickness": 25}),
            PartSpec(id="right", name="Right", kind="side_panel", dimensions_mm={"height": 395, "thickness": 25}),
        ],
        joinery=[JoinerySpec(id="j01", kind="dowel", part_ids=["left", "right"], status="confirmed")],
    )

    issues = validate_manifest(manifest)

    assert [issue.code for issue in issues] == ["basic_checks_passed"]
    assert "承载" not in issues[0].message


def test_unconfirmed_or_missing_joinery_is_a_warning():
    manifest = DesignManifest(
        user_profile=UserProfile(seat_height_mm=420, seat_width_mm=360, seat_depth_mm=380),
        materials={"main": MaterialSpec(kind="solid_wood", stock_thickness_mm=25)},
        joinery=[JoinerySpec(id="j01", kind="unknown", part_ids=["missing", "seat"])],
    )

    codes = {issue.code for issue in validate_manifest(manifest)}

    assert "joinery_part_missing" in codes
    assert "joinery_unconfirmed" in codes
