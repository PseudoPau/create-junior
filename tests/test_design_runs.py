"""Session task lifecycle; no external model calls or live project data."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.workbench import api
from app.workbench.design_runs import DesignRuns, RunConflict
from app.workbench.models import Project
from app.workbench.run_api import router
from app.workbench.store import WorkbenchStore, RevisionConflict


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setenv('CREATE_JUNIOR_AI_PROVIDER', 'session')
    store = WorkbenchStore(tmp_path)
    project = store.save(Project(name="Isolated session test"))
    monkeypatch.setattr(api, "workbench_store", store)
    application = FastAPI()
    application.include_router(router)
    return store, project, DesignRuns(store), TestClient(application)


def candidate():
    return {"scope": "supported", "materials": {"wood": {"name": "Reference wood", "kind": "solid_wood", "grain_axis": "x"}},
            "parts": [{"id": "seat", "name": "Seat", "kind": "seat_board", "material_id": "wood",
                       "size_mm": [400, 24, 215], "position_mm": [0, 400, 0]}]}


def claimed(environment):
    store, project, runs, client = environment
    run = runs.create(project.id, 1, "reconstruct", "Read my reference")
    runs.claim(project.id, run["id"], 1, "session")
    return run


def test_create_is_idempotent_and_different_active_task_conflicts(environment):
    store, project, runs, client = environment
    first = runs.create(project.id, 1, "reconstruct", "chair", "request-1")
    assert runs.create(project.id, 1, "reconstruct", "chair", "request-1")["id"] == first["id"]
    assert runs.create(project.id, 1, "reconstruct", "chair")["id"] == first["id"]
    with pytest.raises(RunConflict):
        runs.create(project.id, 1, "modify", "other")
    assert first["status"] == "waiting_for_session"
    assert store.load(project.id).revision == 1


def test_preview_repair_finish_does_not_adopt_design(environment):
    store, project, runs, client = environment
    run = claimed(environment)
    invalid = candidate()
    invalid["parts"][0]["size_mm"][0] = -10
    first = runs.preview(project.id, run["id"], 1, "session", "Incorrect size", invalid)
    assert first["run"]["attempt"] == 1
    assert first["repairable_issues"][0]["code"] == "proposal_contract"
    second = runs.preview(project.id, run["id"], 1, "session", "Repaired", candidate())
    assert second["repairable_issues"] == []
    with pytest.raises(FileNotFoundError):
        store.proposal(project.id)
    finished = runs.finish(project.id, run["id"], 1, "session", second["proposal"]["id"])
    assert finished["status"] == "ready"
    assert store.proposal(project.id)["id"] == finished["proposal_id"]
    assert store.load(project.id).parts == []
    assert store.load(project.id).revision == 1


def test_cancel_and_revision_change_reject_late_session_result(environment):
    store, project, runs, client = environment
    run = claimed(environment)
    runs.cancel(project.id, run["id"], 1)
    with pytest.raises(RunConflict):
        runs.preview(project.id, run["id"], 1, "session", "Late", candidate())
    newer = runs.create(project.id, 1, "reconstruct", "try again")
    runs.claim(project.id, newer["id"], 1, "session")
    store.change(project.id, 1, {"name": "Changed in browser"})
    assert runs.get(project.id, newer["id"])["status"] == "stale"
    with pytest.raises(RevisionConflict):
        runs.preview(project.id, newer["id"], 1, "session", "Late", candidate())


def test_finish_rejects_design_change_after_successful_preview(environment):
    store, project, runs, client = environment
    run = claimed(environment)
    checked = runs.preview(project.id, run["id"], 1, "session", "Checked", candidate())
    store.change(project.id, 1, {"name": "User changed design"})
    with pytest.raises(RevisionConflict):
        runs.finish(project.id, run["id"], 1, "session", checked["proposal"]["id"])
    with pytest.raises(FileNotFoundError):
        store.proposal(project.id)


def test_adopted_result_does_not_later_appear_as_stale(environment):
    store, project, runs, client = environment
    run = claimed(environment)
    checked = runs.preview(project.id, run["id"], 1, "session", "Checked", candidate())
    proposal = checked["proposal"]
    runs.finish(project.id, run["id"], 1, "session", proposal["id"])
    adopted = store.change(project.id, 1, proposal["patch"])
    runs.mark_result(project.id, proposal["id"], result_revision=adopted.revision)
    assert runs.get(project.id, run["id"])["status"] == "completed"


def test_three_invalid_previews_end_job_without_public_candidate(environment):
    store, project, runs, client = environment
    run = claimed(environment)
    for attempt in range(3):
        result = runs.preview(project.id, run["id"], 1, "session", "Empty design", {})
    assert result["run"]["status"] == "failed"
    assert result["run"]["error"] == "repair_limit"
    with pytest.raises(RunConflict):
        runs.preview(project.id, run["id"], 1, "session", "Fourth", candidate())
    with pytest.raises(FileNotFoundError):
        store.proposal(project.id)


def test_question_answer_preserve_context_and_require_reclaim(environment):
    store, project, runs, client = environment
    run = claimed(environment)
    runs.question(project.id, run["id"], 1, "session", "What is the measured total height?")
    resumed = runs.answer(project.id, run["id"], 1, "82 cm")
    assert resumed["status"] == "waiting_for_session"
    assert resumed["answers"][0]["answer"] == "82 cm"
    assert resumed["text"] == "Read my reference"
    with pytest.raises(RunConflict):
        runs.preview(project.id, run["id"], 1, "session", "Without reclaim", candidate())
    assert runs.claim(project.id, run["id"], 1, "session")["status"] == "running"


@pytest.mark.parametrize("restart", [False, True])
def test_expired_or_restarted_worker_is_not_shown_as_generating(environment, restart):
    store, project, runs, client = environment
    run = claimed(environment)
    saved = runs.get(project.id, run["id"])
    if restart:
        saved["boot_id"] = "prior-server-process"
    else:
        saved["lease_until"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    runs._save(saved)
    assert runs.get(project.id, run["id"])["status"] == "interrupted"


def test_http_input_contract_and_missing_tasks(environment):
    store, project, runs, client = environment
    prefix = "/api/workbench/projects/" + project.id + "/design-runs"
    assert client.post(prefix, json={"expected_revision": 1, "intent": "publish"}).status_code == 422
    response = client.post(prefix, json={"expected_revision": 1, "intent": "reconstruct", "text": "Chair"})
    run = response.json()
    assert response.status_code == 200
    assert client.get(prefix).json()["active"]["id"] == run["id"]
    assert client.get(prefix + "/" + str(uuid4())).status_code == 404
    assert client.post(prefix + "/" + run["id"] + "/preview", json={"summary": "Missing revision"}).status_code == 422
    assert client.post(prefix + "/" + run["id"] + "/cancel", json={"expected_revision": 1}).status_code == 200


def test_context_reports_unread_links_instead_of_claiming_analysis(environment):
    from app.workbench.models import Reference
    store, project, runs, client = environment
    project = store.change(project.id, 1, {"references": [Reference(id=str(uuid4()), name="Unresolved", kind="link", url="https://example.com/chair").model_dump()]})
    run = runs.create(project.id, project.revision, "reconstruct", "Read this link")
    context = runs.context(project.id, run["id"])
    assert context["references"][0]["status"] == "unread"
    assert context["project"]["revision"] == project.revision


def test_reference_context_does_not_follow_external_file_paths(environment, tmp_path):
    from app.workbench.reference_context import reference_path
    store, project, runs, client = environment
    with pytest.raises(ValueError):
        reference_path(store, project, "../../outside")
    with pytest.raises(FileNotFoundError):
        reference_path(store, project, str(uuid4()))


def test_pdf_context_exposes_omitted_pages_and_renders_selected_page(environment):
    pdfium = pytest.importorskip("pypdfium2")
    pytest.importorskip("PIL")
    from app.workbench.models import Reference
    from app.workbench.reference_context import reference_context, render_pdf_page
    store, project, runs, client = environment
    reference_id = str(uuid4())
    folder = store.directory(project.id) / "references"
    folder.mkdir()
    document = pdfium.PdfDocument.new()
    for _ in range(8):
        document.new_page(100, 100).close()
    document.save(folder / reference_id)
    document.close()
    ref = Reference(id=reference_id, name="Drawing.pdf", kind="document", url=f"/api/workbench/projects/{project.id}/references/{reference_id}")
    project = store.change(project.id, 1, {"references": [ref.model_dump()]})
    first = reference_context(store, project)[0]
    assert first["selected_pages"] == [1, 2, 3, 4, 5, 6]
    assert first["omitted_page_count"] == 2
    selected = reference_context(store, project, [7, 8])[0]
    assert selected["selected_pages"] == [7, 8]
    assert [page["page"] for page in selected["pages"]] == [7, 8]
    assert render_pdf_page(store, project, reference_id, 8).startswith(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(ValueError):
        render_pdf_page(store, project, reference_id, 9)


def test_finish_never_overwrites_another_pending_preview(environment):
    store, project, runs, client = environment
    run = claimed(environment)
    checked = runs.preview(project.id, run["id"], 1, "session", "Agent preview", candidate())
    from app.workbench.proposals import build_proposal
    other = build_proposal(project, "User preview", candidate())
    store.save_proposal(project.id, other)
    with pytest.raises(RunConflict):
        runs.finish(project.id, run["id"], 1, "session", checked["proposal"]["id"])
    assert store.proposal(project.id)["id"] == other["id"]


def test_advice_returns_without_candidate_adoption_or_design_revision(environment):
    from copy import deepcopy
    from app.workbench.models import Module
    store, project, runs, client = environment
    body = {"height_mm": 1700, "sitting_height_mm": 900, "hip_width_mm": 380}
    module = Module(id="support", kind="support", name="坐姿支撑", anthropometry=body, affected_part_ids=["seat"])
    project = store.change(project.id, 1, {**candidate(), "modules": [module.model_dump(mode="json")]})
    before = project.model_dump(mode="json")
    run = runs.create(project.id, project.revision, "modify", "Only provide fit advice")
    runs.claim(project.id, run["id"], project.revision, "session")
    modules = deepcopy(before["modules"])
    modules[0]["suggestions"] = [{"key": "seat_height_mm", "value": 410, "reason": "结合原版作小幅调整", "source_ids": [], "anthropometry": body}]
    modules[0]["notes"] = "建议保留座板轮廓。"
    checked = runs.preview(project.id, run["id"], project.revision, "session", "One fit suggestion", {"modules": modules})
    assert checked["proposal"]["result_kind"] == "advice"
    assert checked["repairable_issues"] == []
    finished = runs.finish(project.id, run["id"], project.revision, "session", checked["proposal"]["id"])
    assert finished["status"] == "ready"
    assert finished["result_kind"] == "advice"
    assert finished["proposal_id"] is None
    assert finished["advice_modules"][0]["suggestions"][0]["value"] == 410
    assert store.load(project.id).model_dump(mode="json") == before
    with pytest.raises(FileNotFoundError):
        store.proposal(project.id)
    assert runs.finish(project.id, run["id"], project.revision, "session", checked["proposal"]["id"])["result_kind"] == "advice"


@pytest.mark.parametrize("field, value", [("target", {"seat_height_mm": 410}), ("status", "confirmed"), ("anthropometry", {"height_mm": 1800})])
def test_advice_classifier_does_not_hide_design_or_profile_changes(field, value):
    from copy import deepcopy
    from app.workbench.design_runs import advice_modules
    from app.workbench.models import Module
    project = Project.model_validate({**candidate(), "modules": [Module(id="support", kind="support", name="Support").model_dump(mode="json")]})
    modules = deepcopy(project.model_dump(mode="json")["modules"])
    modules[0][field] = value
    assert advice_modules(project, {"modules": modules}) is None
    assert advice_modules(project, {"modules": project.model_dump(mode="json")["modules"], "name": "Changed"}) is None


def test_pdf_text_extraction_supports_pages_without_context_manager(environment, monkeypatch):
    from types import SimpleNamespace
    from app.workbench import reference_context as references
    from app.workbench.models import Reference
    store, project, runs, client = environment
    reference_id = str(uuid4())
    folder = store.directory(project.id) / "references"
    folder.mkdir()
    (folder / reference_id).write_bytes(b"%PDF-fake fixture")
    ref = Reference(id=reference_id, name="Drawing", kind="document", url=f"/api/workbench/projects/{project.id}/references/{reference_id}")
    project = store.change(project.id, 1, {"references": [ref.model_dump()]})
    closed = []
    class TextPage:
        def get_text_bounded(self):
            return "Chair 820 mm"
        def close(self):
            closed.append("text")
    class Page:
        def get_textpage(self):
            return TextPage()
    class Document:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            closed.append("document")
        def __len__(self):
            return 1
        def __getitem__(self, key):
            return Page()
    monkeypatch.setattr(references, "_pdfium", lambda: SimpleNamespace(PdfDocument=lambda path: Document()))
    result = references.reference_context(store, project)[0]
    assert result["status"] == "read"
    assert result["pages"][0]["text"] == "Chair 820 mm"
    assert closed == ["text", "document"]
