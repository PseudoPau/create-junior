"""The acceptance fixtures must stay executable and same-version reproducible."""
from scripts.verify_two_chairs import cafe_project, ps_project, summary


def test_both_acceptance_chairs_build_ready_packages_with_full_budgets():
    rows = [summary("cafe-chair", cafe_project()), summary("ps2026-reference", ps_project())]
    by_label = {row["label"]: row for row in rows}
    assert by_label["cafe-chair"]["total"] == 968.8
    assert by_label["cafe-chair"]["sheets"] == 1
    assert by_label["cafe-chair"]["reference"] is False
    assert by_label["ps2026-reference"]["total"] == 984.0
    assert by_label["ps2026-reference"]["sheets"] == 1
    assert by_label["ps2026-reference"]["reference"] is True
    for row in rows:
        assert row["package_status"] == "ready"
        assert row["parts"] == 6
        assert row["material"] > 0 and row["processing"] > 0 and row["finish"] > 0


def test_acceptance_summary_declares_reference_and_warnings():
    ps = summary("ps2026-reference", ps_project())
    assert "cam_lock_geometry_approximate" in ps["warnings"]
    cafe = summary("cafe-chair", cafe_project())
    assert "structural_coverage" in cafe["warnings"]
