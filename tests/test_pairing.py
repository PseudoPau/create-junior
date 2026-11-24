"""The pairing suggestion must move a counterpart hole, not silence a check."""
from app.workbench.engine import build_checks
from app.workbench.pairing import pair_joint_preview
from tests.test_workbench_engine import example_project


def codes(project):
    return {check["code"] for check in build_checks(project)}


def test_pair_preview_moves_the_misaligned_counterpart_hole():
    project = example_project()
    project["parts"][1]["features"][0]["u_mm"] = 15
    assert "joint_holes_misaligned" in codes(project)

    preview = pair_joint_preview(project, "join")
    assert preview["pairs"][0]["source"] == "seat_hole"
    assert preview["pairs"][0]["target"] == "support_hole"
    assert preview["pairs"][0]["u_mm"] == 10

    patched = example_project()
    patched["parts"] = preview["patch"]["parts"]
    assert "joint_holes_misaligned" not in codes(patched)


def test_pair_preview_refuses_cam_lock():
    project = example_project()
    project["joints"][0]["kind"] = "cam_lock"
    try:
        pair_joint_preview(project, "join")
    except ValueError as error:
        assert "偏心件" in str(error)
    else:
        raise AssertionError("cam lock must not be silently paired as a screw")
