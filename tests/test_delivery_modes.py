"""Delivery mode is a real decision, not a label on the same package."""
from app.workbench.engine import build_package, build_checks
from tests.test_workbench_engine import example_project


def test_kit_mode_is_valid_and_has_its_own_handoff():
    project = example_project()
    project["fabrication_mode"] = "kit"
    codes = {(item["code"], item["severity"]) for item in build_checks(project)}
    assert ("fabrication_mode_missing", "blocker") not in codes
    assert ("kit_handoff", "info") in codes
    package = build_package(project)
    assert package["delivery"]["mode"] == "kit"
    assert '下料' in package["delivery"]["label"]
    assert package["delivery"]["sections"] == ["发给加工店什么", "我装什么", "验收"]


def test_self_and_shop_have_different_delivery_instructions():
    project = example_project()
    project["fabrication_mode"] = "self"
    self_package = build_package(project)
    assert self_package["delivery"]["sections"] == ["买什么", "怎么切", "怎么装"]
    assert "自己下料" in self_package["delivery"]["cutting"]

    project["fabrication_mode"] = "shop"
    shop_package = build_package(project)
    assert shop_package["delivery"]["sections"] == ["发给加工店什么", "我装什么", "验收"]
    assert "加工店" in shop_package["delivery"]["cutting"]
