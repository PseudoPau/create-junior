"""Contract tests for geometric data, publication gates and machining drawings.

These fixtures are engineering test data, not a verified reference-chair design.
"""

from copy import deepcopy

from app.workbench.engine import build_checks, build_package, draw_part_svg


def example_project():
    return {
        "id": "fixture", "revision": 3, "confirmed_revision": None,
        "acknowledged_limits": False,
        "scope": "supported",
        "references": [{"id": "front", "name": "front.png", "url": "/front"}, {"id": "side", "name": "side.png", "url": "/side"}],
        "scale": {"kind": "target", "confirmed": True, "note": "User-specified target"},
        "fabrication_mode": "self", "requirements": {"load_kg": 80},
        "materials": {"wood": {"name": "Test wood", "kind": "solid_wood", "grain_axis": "x"}},
        "parts": [
            {
                "id": "seat", "name": "Seat", "kind": "seat", "material_id": "wood",
                "size_mm": [100, 20, 100], "position_mm": [0, 100, 0],
                "rotation_deg": [0, 0, 0], "outline_mm": None,
                "features": [{"id": "seat_hole", "kind": "hole", "face": "bottom",
                              "u_mm": 50, "v_mm": 50, "diameter_mm": 4, "depth_mm": 20}],
            },
            {
                "id": "support", "name": "Support", "kind": "leg", "material_id": "wood",
                "size_mm": [20, 80, 100], "position_mm": [0, 50, 0],
                "rotation_deg": [0, 0, 0], "outline_mm": None,
                "features": [{"id": "support_hole", "kind": "hole", "face": "top",
                              "u_mm": 10, "v_mm": 50, "diameter_mm": 3, "depth_mm": 30}],
            },
        ],
        "joints": [{
            "id": "join", "kind": "screw", "part_ids": ["seat", "support"],
            "feature_ids": ["seat_hole", "support_hole"],
            "hardware": [{"name": "Screw", "spec": "4 x 50 mm", "quantity": 1}],
            "assembly_note": "Align the numbered holes, dry assemble, then fasten.",
            "confirmed": True,
        }],
        "evidence": [{"statement": "Hidden joint unknown", "status": "unknown", "source_ids": []}],
        "assumptions": ["The screw connection is an adopted redesign, not observed reference fact."],
    }


def blockers(project):
    return {check["code"] for check in build_checks(project) if check["severity"] == "blocker"}


def test_publication_requires_matching_confirmation_and_acknowledged_limits():
    project = example_project()
    assert not blockers(project)
    assert build_package(project)["status"] == "draft"
    project["confirmed_revision"] = 3
    assert build_package(project)["status"] == "draft"
    project["acknowledged_limits"] = True
    assert build_package(project)["status"] == "ready"
    project["revision"] = 4
    assert build_package(project)["status"] == "draft"


def test_confirmed_version_cannot_override_missing_feature_geometry():
    project = example_project()
    project["confirmed_revision"] = project["revision"]
    project["acknowledged_limits"] = True
    project["parts"][0]["features"][0]["depth_mm"] = 21
    assert "feature_invalid" in blockers(project)
    assert build_package(project)["status"] == "draft"


def test_target_scale_and_unresolved_reference_history_can_coexist():
    project = example_project()
    package = build_package(project)
    assert "scale_unconfirmed" not in blockers(project)
    assert package["evidence"][0]["status"] == "unknown"
    assert "adopted redesign" in package["assumptions"][0]


def test_joint_label_alone_is_not_manufacturing_information():
    project = example_project()
    project["joints"][0]["feature_ids"] = []
    project["joints"][0]["hardware"] = []
    project["joints"][0]["assembly_note"] = ""
    assert {"joint_features_missing", "hardware_missing", "assembly_note_missing"}.issubset(blockers(project))


def test_connected_part_moved_away_invalidates_package():
    project = example_project()
    project["parts"][1]["position_mm"][0] = 500
    assert "joint_parts_separated" in blockers(project)


def test_duplicate_feature_ids_and_foreign_references_are_blocked():
    project = example_project()
    project["parts"][1]["features"][0]["id"] = "seat_hole"
    codes = blockers(project)
    assert "feature_id_invalid" in codes
    assert "joint_feature_missing" in codes


def test_disconnected_part_is_reported_without_fixed_stool_assumptions():
    project = example_project()
    extra = deepcopy(project["parts"][1])
    extra.update(id="backrest", name="Backrest", features=[])
    project["parts"].append(extra)
    assert "assembly_disconnected" in blockers(project)
    assert len(build_package(project)["cut_list"]) == 3


def test_simple_polygon_check_rejects_self_intersection_and_outside_machining():
    project = example_project()
    project["parts"][0]["outline_mm"] = [[0, 0], [100, 100], [0, 100], [100, 0]]
    assert "outline_invalid" in blockers(project)
    project["parts"][0]["outline_mm"] = [[0, 0], [100, 0], [0, 100]]
    project["parts"][0]["features"][0].update(u_mm=85, v_mm=85)
    assert "feature_invalid" in blockers(project)


def test_all_three_dimensions_and_local_face_coordinates_are_in_drawing():
    part = example_project()["parts"][0]
    part["name"] = '<script>alert("unsafe")</script>'
    svg = draw_part_svg(part)
    assert "正视 X/Y" in svg and "俯视 X/Z" in svg and "侧视 Z/Y" in svg
    assert "底面 X/Z" in svg
    assert "U=50 V=50" in svg
    assert "100 × 20 × 100" in svg
    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg


def test_package_uses_parts_without_rederiving_a_template_and_does_not_mutate_input():
    project = example_project()
    before = deepcopy(project)
    package = build_package(project)
    assert project == before
    assert [item["part_id"] for item in package["cut_list"]] == ["seat", "support"]
    assert package["cut_list"][0]["stock_size_mm"] == [100, 20, 100]
    assert package["hardware"] == [{"name": "Screw", "spec": "4 x 50 mm", "quantity": 1}]
    assert package["assembly_steps"][0]["feature_ids"] == ["seat_hole", "support_hole"]
    package["parts"][0]["size_mm"][0] = 999
    assert project["parts"][0]["size_mm"][0] == 100


def test_scope_and_tool_path_do_not_silently_fall_back():
    project = example_project()
    project["scope"] = "unsupported"
    project["scope_reason"] = "Compound curved geometry"
    project["fabrication_mode"] = None
    assert {"scope_unconfirmed", "fabrication_mode_missing"}.issubset(blockers(project))


def test_unimplemented_tenon_stays_blocked_and_strength_is_never_claimed():
    project = example_project()
    project["joints"][0]["kind"] = "mortise_tenon"
    assert "tenon_geometry_missing" in blockers(project)
    package = build_package(project)
    assert "整椅承载与连接强度" in package["coverage"]["not_checked"]
    assert all(check["severity"] != "pass" for check in package["checks"])


def test_hole_offset_and_nonmeeting_drill_segments_are_blocked():
    project = example_project()
    project["parts"][0]["features"][0]["u_mm"] = 60
    assert "joint_holes_misaligned" in blockers(project)
    project = example_project()
    project["parts"][0]["features"][0].update(face="top", depth_mm=5)
    assert "joint_holes_misaligned" in blockers(project)


def test_rotated_assembly_uses_the_same_world_transform_for_holes():
    project = example_project()
    project["parts"][0].update(rotation_deg=[0, 0, 90], position_mm=[-100, 0, 0])
    project["parts"][1].update(rotation_deg=[0, 0, 90], position_mm=[-50, 0, 0])
    assert "joint_holes_misaligned" not in blockers(project)
    assert "joint_parts_separated" not in blockers(project)


def test_dowel_pair_requires_equal_hole_diameter():
    project = example_project()
    project["joints"][0]["kind"] = "dowel"
    assert "joint_holes_misaligned" in blockers(project)
    project["parts"][1]["features"][0]["diameter_mm"] = 4
    assert "joint_holes_misaligned" not in blockers(project)


def test_slot_coordinates_are_minimum_corner_and_inclusive_boundary_is_valid():
    project = example_project()
    feature = project["parts"][0]["features"][0]
    feature.update(kind="slot", u_mm=0, v_mm=0, width_mm=20, length_mm=30, depth_mm=5)
    assert "feature_invalid" not in blockers(project)
    feature["u_mm"] = 81
    assert "feature_invalid" in blockers(project)
    assert "槽 U/V 是最小角" in draw_part_svg(project["parts"][0])


def test_scale_confirmation_requires_a_basis_and_half_lap_cannot_claim_fit():
    project = example_project()
    project["scale"]["note"] = ""
    assert "scale_unconfirmed" in blockers(project)
    project["joints"][0]["kind"] = "half_lap"
    assert "lap_fit_unverified" in blockers(project)


def test_angled_cut_vertices_are_dimensioned_not_only_drawn():
    part = example_project()["parts"][0]
    part["outline_mm"] = [[0, 0], [100, 0], [80, 100], [0, 100]]
    svg = draw_part_svg(part)
    assert "P3: X=80，Z=100 mm" in svg


def test_incomplete_dowel_holes_never_enter_world_matching_or_become_ready():
    from app.workbench.models import Project

    for diameter in (None, -1, 0):
        project = example_project()
        project["id"] = "77545ec0-2770-413f-8ceb-6e681f534407"
        project["joints"][0]["kind"] = "dowel"
        project["parts"][0]["features"][0]["diameter_mm"] = diameter
        project["confirmed_revision"] = project["revision"]
        project["acknowledged_limits"] = True
        candidate = Project.model_validate(project)
        package = build_package(candidate)
        assert package["status"] == "draft"
        assert any(issue["code"] == "feature_invalid" for issue in package["checks"])
        assert "<circle" not in package["drawings"][0]["svg"]


def test_invalid_depth_and_huge_outside_position_are_not_drawn_as_valid_holes():
    for change in ({"depth_mm": -1}, {"u_mm": 1e308}):
        project = example_project()
        project["parts"][0]["features"][0].update(change)
        package = build_package(project)
        assert package["status"] == "draft"
        svg = package["drawings"][0]["svg"]
        assert "<circle" not in svg
        assert 'cx="inf"' not in svg
        assert "草稿无效" in svg


def test_partial_slot_and_invalid_outline_remain_viewable_drafts():
    project = example_project()
    feature = project["parts"][0]["features"][0]
    feature.update(kind="slot", width_mm=None, length_mm=5)
    package = build_package(project)
    assert package["status"] == "draft"
    assert "尺寸待补" in package["drawings"][0]["svg"]
    project["parts"][0]["outline_mm"] = [[0, 0], [100, 0]]
    package = build_package(project)
    assert package["status"] == "draft"
    assert "斜切轮廓至少需要三个顶点" in package["drawings"][0]["svg"]


def test_extreme_but_finite_positions_do_not_overflow_hole_comparison():
    project = example_project()
    project["parts"][0]["position_mm"] = [1e200, 100, 0]
    codes = blockers(project)
    assert "joint_holes_misaligned" in codes
    assert "joint_parts_separated" in codes
    assert build_package(project)["status"] == "draft"


def test_cam_lock_kind_is_recognized_but_pocket_geometry_stays_blocked():
    project = example_project()
    project["joints"][0]["kind"] = "cam_lock"
    codes = blockers(project)
    assert "joint_kind_missing" not in codes
    assert "cam_lock_geometry_missing" in codes
    package = build_package(project)
    assert package["status"] == "draft"
    assert any(check["code"] == "cam_lock_geometry_missing" for check in package["checks"])


def test_cam_lock_pocket_pin_pair_is_approximate_not_missing():
    project = example_project()
    project["joints"][0]["kind"] = "cam_lock"
    project["parts"][0]["features"][0]["diameter_mm"] = 15
    project["parts"][0]["features"][0]["depth_mm"] = 12
    project["parts"][1]["features"][0]["diameter_mm"] = 6.5
    checks = {check["code"]: check for check in build_checks(project)}
    assert "cam_lock_geometry_approximate" in checks
    assert "cam_lock_geometry_missing" not in checks
    assert checks["cam_lock_geometry_approximate"]["severity"] == "warning"
