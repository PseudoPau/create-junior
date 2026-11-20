"""Geometry semantics and selective confirmation dependencies, not UI mocks."""
from copy import deepcopy
from math import cos, radians

import pytest

from app.workbench.demo import cafe_candidate
from app.workbench.measurements import DIMENSION_KEYS, dimension_items, legacy_edit, measurement_fingerprint
from app.workbench.models import Project


def sample():
    project = Project(name="Measurement fixture")
    return Project.model_validate({**project.model_dump(mode="json"), **cafe_candidate(project)["patch"]})


def by_key(project, module_id="sitting-support"):
    return {item["key"]: item for item in dimension_items(project, module_id)}


def test_sample_exposes_five_measured_dimensions_without_rewriting_legacy_targets():
    project = sample()
    before = project.model_dump(mode="json")
    items = dimension_items(project)
    assert tuple(item["key"] for item in items) == DIMENSION_KEYS
    assert [item["current_value"] for item in items] == pytest.approx([450, 400, 215, 0, 100])
    assert items[3]["capability"] == "agent_required"
    assert items[4]["legacy_key"] == "back_angle_deg"
    assert legacy_edit(project, "sitting-support", "seat_back_angle_deg", 105) == ("back_angle_deg", 15)
    assert project.model_dump(mode="json") == before


@pytest.mark.parametrize("tilt", [-5, 5])
def test_seat_tilt_is_signed_and_included_angle_uses_both_surfaces(tilt):
    project = sample()
    seat = next(part for part in project.parts if part.id == "seat")
    seat.rotation_deg = (-tilt, 0, 0)
    items = by_key(project)
    assert items["seat_tilt_deg"]["current_value"] == pytest.approx(tilt)
    assert items["seat_height_mm"]["current_value"] == pytest.approx(438 + 12 * cos(radians(tilt)), abs=1e-6)
    assert items["seat_back_angle_deg"]["current_value"] == pytest.approx(100 - tilt)
    assert items["seat_width_mm"]["current_value"] == 400
    assert all(item["capability"] == "agent_required" for item in items.values())
    with pytest.raises(ValueError, match="Agent"):
        legacy_edit(project, "sitting-support", "seat_back_angle_deg", 105)


def test_module_membership_prevents_cross_chair_measurement_and_ambiguous_default():
    project = sample()
    second = deepcopy(project.modules[0])
    second.id = "second-chair"
    second.affected_part_ids = []
    project.modules.append(second)
    assert all(item["current_value"] is None for item in dimension_items(project))
    assert by_key(project)["seat_height_mm"]["current_value"] == 450
    assert all(item["current_value"] is None for item in dimension_items(project, "second-chair"))


def test_missing_or_ambiguous_back_does_not_hide_known_seat_dimensions():
    project = sample()
    project.modules[0].affected_part_ids.remove("back")
    items = by_key(project)
    assert items["seat_width_mm"]["current_value"] == 400
    assert items["seat_back_angle_deg"]["status"] == "unknown"
    assert items["seat_back_angle_deg"]["fingerprint"] is None
    project = sample()
    duplicate = deepcopy(next(part for part in project.parts if part.id == "back"))
    duplicate.id = "other-back"
    duplicate.features = []
    project.parts.append(duplicate)
    project.modules[0].affected_part_ids.append(duplicate.id)
    joint = deepcopy(project.joints[0])
    joint.id = "other-back-joint"
    joint.part_ids = ["seat", "other-back"]
    project.joints.append(joint)
    assert by_key(project)["seat_back_angle_deg"]["current_value"] is None


def test_irregular_or_side_sloped_seat_requires_an_explicit_measurement_basis():
    project = sample()
    seat = next(part for part in project.parts if part.id == "seat")
    seat.outline_mm = [(0, 0), (400, 0), (200, 215)]
    assert all(item["status"] == "unknown" for item in dimension_items(project))
    seat.outline_mm = None
    seat.rotation_deg = (0, 0, 5)
    assert all(item["status"] == "unknown" for item in dimension_items(project))


def test_fingerprint_tracks_changed_dimension_and_body_but_not_revision_or_timestamp():
    project = sample()
    keys = DIMENSION_KEYS
    signature = lambda key: measurement_fingerprint(project, "sitting-support", key)
    before = {key: signature(key) for key in keys}
    project.revision += 1
    project.updated_at = "2030-01-01T00:00:00Z"
    assert {key: signature(key) for key in keys} == before
    seat = next(part for part in project.parts if part.id == "seat")
    seat.size_mm = (420, 24, 215)
    assert signature("seat_width_mm") != before["seat_width_mm"]
    assert signature("seat_height_mm") == before["seat_height_mm"]
    assert signature("seat_back_angle_deg") == before["seat_back_angle_deg"]
    after_size = {key: signature(key) for key in keys}
    project.modules[0].anthropometry["hip_breadth_mm"] = 420
    assert all(signature(key) != after_size[key] for key in keys)


def test_unknown_dimension_key_is_not_confirmable():
    with pytest.raises(ValueError, match="未知"):
        measurement_fingerprint(sample(), "sitting-support", "back_angle_deg")
