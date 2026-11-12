from app.airport.stool import DesignIncomplete, build_box_plan, derive_stool_parts, derive_stool_proposal
from app.domain.models import DesignManifest, MaterialSpec, UserProfile


def manifest():
    return DesignManifest(
        name="AA Stool",
        user_profile=UserProfile(seat_height_mm=420, seat_width_mm=360, seat_depth_mm=380),
        materials={"main": MaterialSpec(kind="solid_wood", name="Pine", stock_thickness_mm=25)},
    )


def test_build_box_plan_uses_scene_units():
    plan = build_box_plan(manifest(), 0.001)

    assert plan["parts"][0]["name"] == "Seat"
    assert plan["parts"][0]["max"] == [0.18, 0.19, 0.42]
    assert len(plan["parts"]) == 3


def test_build_box_plan_requires_confirmed_dimensions():
    incomplete = DesignManifest(materials={"main": MaterialSpec(stock_thickness_mm=25)})

    try:
        build_box_plan(incomplete, 0.001)
    except DesignIncomplete as error:
        assert "seat_height_mm" in str(error)
    else:
        raise AssertionError("incomplete design should not create Airport geometry")


def test_derive_stool_parts_from_dimensions():
    parts = derive_stool_parts(manifest())

    assert [part.id for part in parts] == ["seat", "side_left", "side_right"]
    assert parts[0].dimensions_mm["height"] == 25
    assert parts[1].dimensions_mm["height"] == 395


def test_derive_stool_proposal_exposes_joinery_as_unconfirmed():
    parts, joinery = derive_stool_proposal(manifest())

    assert len(parts) == 3
    assert [joint.status for joint in joinery] == ["candidate", "candidate"]
    assert all(joint.kind == "unknown" for joint in joinery)
