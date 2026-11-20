from copy import deepcopy

from app.workbench.review_groups import review_groups


def part(pid, *, material="oak", size=(400, 24, 215), rotation=(0, 0, 0), features=None):
    return {"id": pid, "name": pid, "kind": "board", "material_id": material,
            "size_mm": size, "position_mm": (0, 0, 0), "rotation_deg": rotation,
            "outline_mm": None, "plane_cuts": [], "features": features or []}


def project(parts, joints=None, materials=None):
    return {"parts": parts, "joints": joints or [], "materials": materials or {
        "oak": {"name": "白蜡木", "kind": "solid_wood", "grain_axis": "x", "properties": {}}}}


def test_board_groups_merge_exact_symmetric_members_and_keep_axes():
    result = review_groups(project([part("left"), part("right")]))
    groups = result["board_groups"]
    assert len(groups) == 1 and groups[0]["part_ids"] == ["left", "right"]
    assert groups[0]["dimensions"] == {"length_mm": 215, "width_mm": 400, "thickness_mm": 24,
        "axes": {"length": "local_z", "width": "local_x", "thickness": "local_y"}}


def test_board_groups_do_not_merge_different_holes_or_materials():
    hole = {"id": "h1", "role": "connection", "kind": "hole", "face": "top", "u_mm": 20,
            "v_mm": 20, "diameter_mm": 8, "width_mm": None, "length_mm": None, "depth_mm": 10,
            "entry_mm": None, "direction_local": None}
    result = review_groups(project([part("left", features=[hole]), part("right", material="oak2")], materials={
        "oak": {"name": "白蜡木", "kind": "solid_wood", "grain_axis": "x", "properties": {}},
        "oak2": {"name": "桦木板", "kind": "panel", "grain_axis": "x", "properties": {}}}))
    assert len(result["board_groups"]) == 2


def test_translation_does_not_change_group_fingerprint_or_dimensions():
    first = part("a")
    moved = deepcopy(first); moved["position_mm"] = (900, 330, -100)
    left = review_groups(project([first]))["board_groups"][0]
    right = review_groups(project([moved]))["board_groups"][0]
    assert left["fingerprint"] == right["fingerprint"] and left["dimensions"] == right["dimensions"]


def test_node_groups_merge_same_method_and_keep_member_ids():
    joints = [{"id": "j-left", "name": "座板左侧", "kind": "screw", "part_ids": ["a", "b"], "feature_ids": ["fa", "fb"], "hardware": [], "assembly_note": "拧紧", "confirmed": False},
              {"id": "j-right", "name": "座板右侧", "kind": "screw", "part_ids": ["a", "b"], "feature_ids": ["fa", "fb"], "hardware": [], "assembly_note": "拧紧", "confirmed": False}]
    groups = review_groups(project([part("a"), part("b")], joints))["node_groups"]
    assert len(groups) == 1 and groups[0]["joint_ids"] == ["j-left", "j-right"] and groups[0]["quantity"] == 2


def test_node_groups_split_different_method():
    joints = [{"id": "j1", "name": "一", "kind": "screw", "part_ids": ["a", "b"], "feature_ids": [], "hardware": [], "assembly_note": "", "confirmed": False},
              {"id": "j2", "name": "二", "kind": "dowel", "part_ids": ["a", "b"], "feature_ids": [], "hardware": [], "assembly_note": "", "confirmed": False}]
    assert len(review_groups(project([part("a"), part("b")], joints))["node_groups"]) == 2


def test_node_confirmation_fingerprint_follows_referenced_hole_and_relative_pose():
    holes = [{"id": key, "kind": "hole", "face": "top", "u_mm": u,
              "v_mm": 20, "diameter_mm": 8, "depth_mm": 10}
             for key, u in [("first", 20), ("second", 80)]]
    a, b = part("a", features=holes), part("b")
    joint = {"id": "j", "kind": "screw", "part_ids": ["a", "b"],
             "feature_ids": ["first"], "hardware": [], "assembly_note": "拧紧"}
    initial = project([a, b], [joint])
    original = review_groups(initial)["node_groups"][0]["fingerprint"]
    different_hole = deepcopy(initial)
    different_hole["joints"][0]["feature_ids"] = ["second"]
    assert review_groups(different_hole)["node_groups"][0]["fingerprint"] != original
    moved = deepcopy(initial)
    moved["parts"][1]["position_mm"] = (100, 0, 0)
    assert review_groups(moved)["node_groups"][0]["fingerprint"] != original


def test_group_ids_stable_under_source_order_and_material_change_invalidates_fingerprint():
    a, b = part("a"), part("b")
    original = review_groups(project([a, b]))["board_groups"][0]
    reordered = review_groups(project([b, a]))["board_groups"][0]
    assert reordered["id"] == original["id"]
    changed = project([a, b])
    changed["materials"]["oak"]["grain_axis"] = "z"
    assert review_groups(changed)["board_groups"][0]["fingerprint"] != original["fingerprint"]


def test_real_sample_mirrors_group_by_geometry_with_correct_stock_axes():
    from app.workbench.demo import cafe_candidate
    from app.workbench.models import Project
    data = cafe_candidate(Project())['patch']
    result = review_groups(data)
    assert sorted(group['quantity'] for group in result['board_groups']) == [1, 1, 2, 2]
    assert sorted(group['quantity'] for group in result['node_groups']) == [1, 2, 2]
    sides = next(group for group in result['board_groups'] if 'side_left' in group['part_ids'])
    assert sides['part_ids'] == ['side_left', 'side_right']
    assert sides['dimensions'] == {'length_mm': 426, 'width_mm': 170, 'thickness_mm': 24,
        'axes': {'length': 'local_z', 'width': 'local_y', 'thickness': 'local_x'}}
    # A different diameter at only one mirrored end makes both the board and
    # connected node stop being equivalent to their counterparts.
    changed = deepcopy(data)
    next(p for p in changed['parts'] if p['id'] == 'side_right')['features'][0]['diameter_mm'] += 1
    split = review_groups(changed)
    assert len(split['board_groups']) == 5
    assert len(split['node_groups']) > 3


def test_group_consent_tracks_every_member_note_and_handed_hole_not_representative_only():
    from app.workbench.demo import cafe_candidate
    from app.workbench.models import Project
    data = cafe_candidate(Project())['patch']
    before = review_groups(data)
    group = next(g for g in before['node_groups'] if 'seat_right' in g['joint_ids'])
    changed = deepcopy(data)
    next(j for j in changed['joints'] if j['id'] == 'seat_right')['assembly_note'] += ' 使用另一种预钻顺序。'
    after = next(g for g in review_groups(changed)['node_groups'] if g['id'] == group['id'])
    assert after['quantity'] == 2
    assert after['fingerprint'] != group['fingerprint']
    assert len(after['assembly_notes']) == 2
