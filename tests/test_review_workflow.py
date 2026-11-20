"""Review facts persist with their geometry; package exports use the same revision.

No online AI or browser printing is required. Only PDF rendering is substituted;
the export regression exercises the real package builder and ZIP contents.
"""
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.workbench import api, exports
from app.workbench.demo import cafe_candidate
from app.workbench.design_runs import DesignRuns
from app.workbench.models import Project
from app.workbench.review import review_projection
from app.workbench.store import WorkbenchStore


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    store = WorkbenchStore(tmp_path)
    monkeypatch.setattr(api, "workbench_store", store)
    original = Project(name="Review fixture", references=[{
        "id": "sample-reference", "kind": "note", "name": "Reference",
        "text": "Explicit CAFE sample for review lifecycle tests",
    }])
    data = {**original.model_dump(mode="json"), **cafe_candidate(original)["patch"]}
    data["scale"]["confirmed"] = True
    for joint in data["joints"]:
        joint["confirmed"] = False
    project = store.save(Project.model_validate(data))
    return TestClient(app), store, project, "/api/workbench/projects/" + project.id


def start(client, url):
    project = client.get(url).json()
    response = client.post(url + "/review/start", json={"expected_revision": project["revision"]})
    assert response.status_code == 200, response.text
    return response.json()


def choose(review, category, key=None):
    name = {"dimension": "dimensions", "board": "board_groups", "node": "node_groups"}[category]
    return next(item for item in review[name] if key is None or item.get("key") == key)


def confirm(client, url, review, item):
    response = client.post(url + "/review/confirm", json={
        "expected_revision": review["revision"], "category": item["category"],
        "id": item["id"], "fingerprint": item["fingerprint"], "decision": "keep",
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_review_read_is_pure_and_old_flags_do_not_become_new_consent(workspace):
    client, store, project, url = workspace
    before = store.load(project.id).model_dump(mode="json")
    legacy = client.get(url + "/review").json()
    assert legacy["enabled"] is False
    assert store.load(project.id).model_dump(mode="json") == before
    modules = before["modules"]
    modules[0]["confirmations"] = {item["key"]: True for item in legacy["dimensions"]}
    store.change(project.id, project.revision, {"modules": modules})
    review = start(client, url)
    assert review["enabled"] is True
    assert len(review["dimensions"]) == 5
    assert all(not item["confirmed"] for item in review["dimensions"])
    assert review["complete"] is False


def test_confirmed_dimensions_survive_restart_and_unrelated_rename(workspace):
    client, store, project, url = workspace
    review = start(client, url)
    review = confirm(client, url, review, choose(review, "dimension", "seat_height_mm"))
    reloaded = WorkbenchStore(store.root).load(project.id)
    assert choose(review_projection(reloaded), "dimension", "seat_height_mm")["confirmed"] is True
    assert reloaded.review_state.confirmations["dimension:sitting-support:seat_height_mm"].revision == review["revision"]
    renamed = store.change(project.id, review["revision"], {"name": "Renamed only"})
    assert choose(review_projection(renamed), "dimension", "seat_height_mm")["confirmed"] is True


def test_geometry_edit_invalidates_affected_dimension_without_resetting_width(workspace):
    client, store, project, url = workspace
    review = start(client, url)
    for key in ("seat_height_mm", "seat_width_mm"):
        review = confirm(client, url, review, choose(review, "dimension", key))
    parts = store.load(project.id).model_dump(mode="json")["parts"]
    next(part for part in parts if part["id"] == "seat")["position_mm"][1] += 10
    updated = store.change(project.id, review["revision"], {"parts": parts})
    after = review_projection(updated)
    assert choose(after, "dimension", "seat_height_mm")["confirmed"] is False
    assert choose(after, "dimension", "seat_width_mm")["confirmed"] is True


def test_first_confirmation_preserves_remaining_advice_without_changing_geometry(workspace):
    client, store, project, url = workspace
    review = start(client, url)
    before = store.load(project.id).model_dump(mode="json")
    modules = store.load(project.id).model_dump(mode="json")["modules"]
    suggestions = [{"key": key, "value": value, "reason": "Explicit test suggestion",
                    "source_ids": [], "anthropometry": modules[0]["anthropometry"]}
                   for key, value in (("seat_height_mm", 430), ("seat_width_mm", 440))]
    modules[0]["suggestions"] = suggestions
    runner = DesignRuns(store)
    run = runner.create(project.id, review["revision"], "modify", "Suggest fit dimensions",
                        requested_result_kind="advice", execution_mode="session")
    worker = "review-advice-test"
    runner.claim(project.id, run["id"], review["revision"], worker)
    preview = runner.preview(project.id, run["id"], review["revision"], worker,
                             "Two suggestions for review", {"modules": modules})
    assert preview["repairable_issues"] == []
    result = runner.finish(project.id, run["id"], review["revision"], worker, preview["proposal"]["id"])
    assert result["result_kind"] == "advice"
    assert store.load(project.id).model_dump(mode="json") == before

    review = confirm(client, url, review, choose(review, "dimension", "seat_height_mm"))
    persisted = WorkbenchStore(store.root).load(project.id).model_dump(mode="json")
    assert persisted["modules"][0]["suggestions"] == suggestions
    assert persisted["parts"] == before["parts"]
    assert persisted["joints"] == before["joints"]
    assert persisted["modules"][0]["target"] == before["modules"][0]["target"]
    assert persisted["baseline_revision"] == before["baseline_revision"]
    assert runner.get(project.id, run["id"])["status"] == "stale"
    response = client.get(url + "/modules/sitting-support/comparison?canonical=true")
    assert response.status_code == 200, response.text
    width = next(item for item in response.json()["items"] if item["key"] == "seat_width_mm")
    assert width["suggested_value"] == 440
    assert choose(review, "dimension", "seat_width_mm")["confirmed"] is False


def test_stale_revision_or_fingerprint_cannot_record_consent(workspace):
    client, store, project, url = workspace
    review = start(client, url)
    item = choose(review, "dimension", "seat_height_mm")
    body = {"expected_revision": review["revision"], "category": "dimension",
            "id": item["id"], "fingerprint": item["fingerprint"]}
    current = store.change(project.id, review["revision"], {"name": "New version"})
    assert client.post(url + "/review/confirm", json=body).status_code == 409
    parts = current.model_dump(mode="json")["parts"]
    next(part for part in parts if part["id"] == "seat")["position_mm"][1] += 10
    current = store.change(project.id, current.revision, {"parts": parts})
    body["expected_revision"] = current.revision
    before = current.model_dump(mode="json")
    assert client.post(url + "/review/confirm", json=body).status_code == 409
    assert store.load(project.id).model_dump(mode="json") == before


def test_board_thickness_change_reopens_board_and_connected_node_review(workspace):
    client, store, project, url = workspace
    review = start(client, url)
    board = next(item for item in review["board_groups"] if "seat" in item["part_ids"])
    review = confirm(client, url, review, board)
    node = next(item for item in review["node_groups"] if "seat" in item["part_ids"])
    review = confirm(client, url, review, node)
    parts = store.load(project.id).model_dump(mode="json")["parts"]
    next(part for part in parts if part["id"] == "seat")["size_mm"][1] += 2
    current = store.change(project.id, review["revision"], {"parts": parts})
    after = review_projection(current)
    assert next(item for item in after["board_groups"] if "seat" in item["part_ids"])["confirmed"] is False
    assert all(not item["confirmed"] for item in after["node_groups"] if "seat" in item["part_ids"])


def test_patch_cannot_forge_review_confirmation(workspace):
    client, store, project, url = workspace
    review = start(client, url)
    item = choose(review, "dimension", "seat_height_mm")
    forged = {"version": 1, "confirmations": {"dimension:" + item["id"]: {
        "fingerprint": item["fingerprint"], "revision": review["revision"], "decision": "keep",
    }}}
    response = client.put(url, json={"expected_revision": review["revision"],
                                    "patch": {"review_state": forged}})
    assert response.status_code == 422
    assert store.load(project.id).revision == review["revision"]
    # Even an internal patch must retain server-owned prior facts, never import
    # claims from the incoming candidate or a restored snapshot.
    updated = store.change(project.id, review["revision"], {"review_state": forged})
    assert updated.review_state.confirmations == {}
    assert choose(review_projection(updated), "dimension", "seat_height_mm")["confirmed"] is False


def test_node_review_records_group_consent_in_one_revision(workspace):
    client, store, project, url = workspace
    review = start(client, url)
    item = choose(review, "node")
    selected_ids = set(item["joint_ids"])
    result = confirm(client, url, review, item)
    current = store.load(project.id)
    assert current.revision == review["revision"] + 1 == result["revision"]
    assert {joint.id for joint in current.joints if joint.confirmed} == selected_ids
    assert next(group for group in result["node_groups"] if group["id"] == item["id"])["confirmed"] is True


def test_review_enabled_export_uses_real_package_builder_and_persisted_revision(workspace, monkeypatch):
    client, store, project, url = workspace
    review = start(client, url)
    blocked = client.post(url + "/exports", json={"expected_revision": review["revision"]})
    assert blocked.status_code == 409
    assert any(issue["code"] == "workflow_review_pending" for issue in blocked.json()["detail"]["checks"])
    for name in ("dimensions", "board_groups", "node_groups"):
        for item in list(review[name]):
            review = confirm(client, url, review, item)
    assert review["complete"] is True

    async def pdf(document):
        assert document
        return b"%PDF-1.4\nreview-export-fixture"

    monkeypatch.setattr(exports, "render_pdf", pdf)
    before = store.load(project.id).model_dump(mode="json")
    exported = client.post(url + "/exports", json={"expected_revision": review["revision"]})
    assert exported.status_code == 200, exported.text
    record = exported.json()
    assert record["revision"] == review["revision"]
    assert record["package_snapshot"]["review_blockers"] == []
    assert store.load(project.id).model_dump(mode="json") == before
    archive_bytes = client.get(record["download_url"]).content
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        snapshot = json.loads(archive.read("model/design.json"))
        assert snapshot["revision"] == review["revision"]
        assert snapshot["review_state"] == before["review_state"]
        assert "drawings.pdf" in archive.namelist()
    store.change(project.id, review["revision"], {"name": "Next design"})
    assert client.get(record["download_url"]).content == archive_bytes
    assert client.get(url + "/exports").json()["exports"][0]["current"] is False
