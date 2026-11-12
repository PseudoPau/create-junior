from app.domain.models import DesignManifest, MaterialSpec, UserProfile
from app.materials.library import MATERIAL_PRESETS, estimate_seat_load, resolve_material


def test_builtin_material_is_conservative_and_overridable():
    preset = resolve_material(MaterialSpec(kind="solid_wood", name="pine", properties={"elastic_modulus_mpa": 9000}))

    assert preset is not None
    assert preset.conservative is True
    assert preset.elastic_modulus_mpa == 9000
    assert preset.source == "user override"


def test_load_estimate_reports_unknown_for_unlisted_material():
    manifest = DesignManifest(
        user_profile=UserProfile(seat_width_mm=360, seat_depth_mm=380, estimated_load_kg=80),
        materials={"main": MaterialSpec(kind="solid_wood", name="local wood", stock_thickness_mm=25)},
    )

    result = estimate_seat_load(manifest)

    assert result.status == "unknown"
    assert result.issues[0].code == "material_properties_missing"


def test_load_estimate_is_preliminary_and_exposes_assumptions():
    manifest = DesignManifest(
        user_profile=UserProfile(seat_width_mm=360, seat_depth_mm=380, estimated_load_kg=80),
        materials={"main": MaterialSpec(kind="solid_wood", name="pine", stock_thickness_mm=25)},
    )

    result = estimate_seat_load(manifest)

    assert result.status in {"pass", "warning"}
    assert result.bending_stress_mpa is not None
    assert result.allowable_stress_mpa is not None
    assert any("不是工程安全认证" in assumption for assumption in result.assumptions)
