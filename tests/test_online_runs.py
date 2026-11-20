"""Online orchestration with injected providers; no external calls or live projects."""
import asyncio
import base64
from copy import deepcopy
import json
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.workbench import api, online_runs
from app.workbench.ai import UnavailableDesigner, PrototypeDesigner
from app.workbench.design_runs import DesignRuns, RunConflict
from app.workbench.models import Project, Reference, Module
from app.workbench.run_api import router
from app.workbench.store import WorkbenchStore


def candidate():
    return {"scope": "supported", "materials": {"wood": {"name": "Wood", "kind": "solid_wood", "grain_axis": "x"}},
            "parts": [{"id": "seat", "name": "Seat", "kind": "seat_board", "material_id": "wood",
                       "size_mm": [400, 24, 215], "position_mm": [0, 400, 0]}]}


class FakeProvider:
    name = "fake_online"

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def generate(self, content):
        self.calls.append(deepcopy(content))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return deepcopy(response)


@pytest.fixture
def environment(tmp_path):
    store = WorkbenchStore(tmp_path)
    reference = Reference(id=str(uuid4()), name="Brief", kind="note", text="Restore a straight-board wooden chair.")
    project = store.save(Project(name="Online test", references=[reference]))
    return store, project, DesignRuns(store)


def create_run(environment, **kwargs):
    store, project, service = environment
    return service.create(project.id, project.revision, "reconstruct", "Restore this chair", execution_mode="online", **kwargs)


async def drain(service, run):
    task = online_runs._tasks.get(online_runs._key(service, run["project_id"], run["id"]))
    if task is not None:
        await task
    return service.get(run["project_id"], run["id"])


def test_automatic_generation_is_idempotent_and_never_adopts(environment):
    store, project, service = environment
    run = create_run(environment, client_request_id="once")
    provider = FakeProvider({"summary": "Candidate", "patch": candidate(), "provider": "untrusted"})

    async def scenario():
        first = online_runs.start_online_run(service, run, provider)
        duplicate = service.create(project.id, 1, "reconstruct", "Restore this chair", "once", execution_mode="online")
        second = online_runs.start_online_run(service, duplicate, provider)
        assert first["worker_id"] == second["worker_id"]
        return await drain(service, run)

    finished = asyncio.run(scenario())
    assert finished["status"] == "ready"
    assert finished["result_kind"] == "design"
    assert len(provider.calls) == 1
    proposal = store.proposal(project.id)
    assert proposal["source"] == "ai:fake_online"
    assert proposal["provider"] == "fake_online"
    assert store.load(project.id).revision == 1
    assert store.load(project.id).parts == []


@pytest.mark.parametrize("provider", [UnavailableDesigner("Secret-bearing custom reason"), PrototypeDesigner()])
def test_unavailable_or_prototype_fails_before_background_work(environment, provider):
    store, project, service = environment
    run = create_run(environment)
    result = online_runs.start_online_run(service, run, provider)
    assert result["status"] == "failed"
    assert result["error"] == "provider_unavailable"
    assert "Secret-bearing" not in json.dumps(result)
    assert online_runs._key(service, project.id, run["id"]) not in online_runs._tasks


def test_http_missing_online_configuration_returns_terminal_failure(environment, monkeypatch):
    store, project, service = environment
    monkeypatch.setattr(api, "workbench_store", store)
    monkeypatch.setenv("CREATE_JUNIOR_AI_PROVIDER", "openai")
    monkeypatch.delenv("CREATE_JUNIOR_AI_API_KEY", raising=False)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post(f"/api/workbench/projects/{project.id}/design-runs", json={"expected_revision": 1})
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error"] == "provider_unavailable"


def test_session_http_mode_remains_manual(environment, monkeypatch):
    store, project, service = environment
    monkeypatch.setattr(api, "workbench_store", store)
    monkeypatch.setenv("CREATE_JUNIOR_AI_PROVIDER", "session")
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post(f"/api/workbench/projects/{project.id}/design-runs", json={"expected_revision": 1})
    assert response.json()["status"] == "waiting_for_session"
    assert response.json()["execution_mode"] == "session"


def test_online_task_cannot_be_claimed_by_manual_session(environment):
    store, project, service = environment
    run = create_run(environment)
    with pytest.raises(RunConflict):
        service.claim(project.id, run["id"], 1, "session")


@pytest.mark.parametrize("answered", [False, True])
def test_restart_between_waiting_and_claim_does_not_strand_online_task(environment, monkeypatch, answered):
    from app.workbench import design_runs
    store, project, service = environment
    run = create_run(environment)
    if answered:
        service.claim(project.id, run["id"], 1, "online:test", provider_name="fake_online")
        service.question(project.id, run["id"], 1, "online:test", "Seat width?")
        service.answer(project.id, run["id"], 1, "400 mm")
    monkeypatch.setattr(design_runs, "BOOT_ID", "new-process")
    assert service.get(project.id, run["id"])["status"] == "interrupted"
    assert service.list(project.id)["active"] is None


@pytest.mark.parametrize("request_id", [None, "same-request"])
def test_switching_provider_mode_does_not_reuse_a_manual_wait(environment, request_id):
    store, project, service = environment
    service.create(project.id, 1, "reconstruct", "Restore this chair", request_id)
    with pytest.raises(RunConflict, match="执行通道已经切换"):
        service.create(project.id, 1, "reconstruct", "Restore this chair", request_id, execution_mode="online")


def test_invalid_geometry_is_repaired_through_preview(environment):
    store, project, service = environment
    invalid = candidate()
    invalid["parts"][0]["size_mm"][0] = -1
    provider = FakeProvider({"summary": "Bad", "patch": invalid}, {"summary": "Fixed", "patch": candidate()})
    run = create_run(environment)

    async def scenario():
        online_runs.start_online_run(service, run, provider)
        return await drain(service, run)

    result = asyncio.run(scenario())
    assert result["status"] == "ready"
    assert result["attempt"] == 2
    assert "repairable_issues" in provider.calls[1][-1]["text"]
    assert all(set(item) <= {"type", "text", "image_url"} for item in provider.calls[1])


def test_three_failed_previews_stop_without_candidate(environment):
    store, project, service = environment
    provider = FakeProvider(*[{"summary": "Missing geometry", "patch": {}}] * 3)
    run = create_run(environment)

    async def scenario():
        online_runs.start_online_run(service, run, provider)
        return await drain(service, run)

    result = asyncio.run(scenario())
    assert result["status"] == "failed" and result["attempt"] == 3
    assert len(provider.calls) == 3
    with pytest.raises(FileNotFoundError):
        store.proposal(project.id)


def test_advice_returns_without_model_change(environment):
    store, project, service = environment
    module = Module(id="support", kind="support", name="Support", affected_part_ids=["seat"])
    project = store.change(project.id, 1, {**candidate(), "modules": [module.model_dump(mode="json")]})
    modules = deepcopy(project.model_dump(mode="json")["modules"])
    modules[0]["notes"] = "Keep the original seat outline."
    provider = FakeProvider({"summary": "Fit guidance", "patch": {"modules": modules}})
    run = service.create(project.id, project.revision, "modify", "Only advice", requested_result_kind="advice", execution_mode="online")

    async def scenario():
        online_runs.start_online_run(service, run, provider)
        return await drain(service, run)

    result = asyncio.run(scenario())
    assert result["status"] == "ready" and result["result_kind"] == "advice"
    assert result["advice_modules"][0]["notes"] == modules[0]["notes"]
    assert result["proposal_id"] is None
    assert store.load(project.id).model_dump() == project.model_dump()
    with pytest.raises(FileNotFoundError):
        store.proposal(project.id)


def test_advice_request_rejects_geometry_and_is_part_of_idempotency(environment):
    store, project, service = environment
    run = create_run(environment, client_request_id="fit", requested_result_kind="advice")
    with pytest.raises(RunConflict):
        service.create(project.id, 1, "reconstruct", "Restore this chair", "fit", requested_result_kind="design")
    provider = FakeProvider(*[{"summary": "Changed geometry", "patch": candidate()}] * 3)

    async def scenario():
        online_runs.start_online_run(service, run, provider)
        return await drain(service, run)

    result = asyncio.run(scenario())
    assert result["status"] == "failed" and result["error"] == "repair_limit"
    assert store.load(project.id).revision == 1


def test_question_then_answer_reschedules_same_task(environment):
    store, project, service = environment
    provider = FakeProvider({"question": "What is the measured seat width?"}, {"summary": "Candidate", "patch": candidate()})
    run = create_run(environment)

    async def scenario():
        online_runs.start_online_run(service, run, provider)
        asked = await drain(service, run)
        assert asked["status"] == "needs_input"
        answered = service.answer(project.id, run["id"], 1, "400 mm")
        online_runs.start_online_run(service, answered, provider)
        return await drain(service, run)

    result = asyncio.run(scenario())
    assert result["status"] == "ready"
    assert result["answers"][0]["answer"] == "400 mm"
    assert "400 mm" in provider.calls[1][0]["text"]


@pytest.mark.parametrize("change", ["cancel", "revision"])
def test_late_result_cannot_overwrite_cancel_or_new_revision(environment, change):
    store, project, service = environment
    run = create_run(environment)

    class SuspendedProvider:
        name = "fake_online"

        async def generate(self, content):
            entered.set()
            await release.wait()
            return {"summary": "Late candidate", "patch": candidate()}

    async def scenario():
        nonlocal entered, release
        entered, release = asyncio.Event(), asyncio.Event()
        online_runs.start_online_run(service, run, SuspendedProvider())
        await entered.wait()
        if change == "cancel":
            service.cancel(project.id, run["id"], 1)
        else:
            store.change(project.id, 1, {"name": "Browser changed design"})
        release.set()
        return await drain(service, run)

    entered = release = None
    result = asyncio.run(scenario())
    assert result["status"] == ("cancelled" if change == "cancel" else "stale")
    with pytest.raises(FileNotFoundError):
        store.proposal(project.id)


def test_cancel_stops_inflight_provider(environment):
    store, project, service = environment
    run = create_run(environment)

    async def scenario():
        entered, stopped = asyncio.Event(), asyncio.Event()

        class WaitingProvider:
            name = "fake_online"

            async def generate(self, content):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()

        online_runs.start_online_run(service, run, WaitingProvider())
        task = online_runs._tasks[online_runs._key(service, project.id, run["id"])]
        await entered.wait()
        service.cancel(project.id, run["id"], 1)
        online_runs.cancel_online_run(service, project.id, run["id"])
        await asyncio.gather(task, return_exceptions=True)
        assert stopped.is_set()
        assert service.get(project.id, run["id"])["status"] == "cancelled"

    asyncio.run(scenario())


def test_total_deadline_ends_waiting_provider(environment):
    store, project, service = environment
    run = create_run(environment)
    claimed = service.claim(project.id, run["id"], 1, "online:test", provider_name="fake_online")

    class NeverProvider:
        name = "fake_online"

        async def generate(self, content):
            await asyncio.Event().wait()

    asyncio.run(online_runs.execute_online_run(service, claimed, "online:test", NeverProvider(), timeout_seconds=0.05))
    result = service.get(project.id, run["id"])
    assert result["status"] == "failed" and result["error"] == "online_timeout"


@pytest.mark.parametrize("error", [ValueError("SECRET_TOKEN"), RuntimeError("SECRET_TOKEN"),
    httpx.HTTPStatusError("SECRET_TOKEN", request=httpx.Request("POST", "https://example.com"), response=httpx.Response(401))])
def test_failure_never_exposes_provider_secrets(environment, error):
    store, project, service = environment
    run = create_run(environment)

    async def scenario():
        online_runs.start_online_run(service, run, FakeProvider(error))
        return await drain(service, run)

    result = asyncio.run(scenario())
    assert result["status"] == "failed"
    assert "SECRET_TOKEN" not in json.dumps(result)


def test_unread_link_is_resolved_without_project_mutation(environment, monkeypatch):
    store, project, service = environment
    reference = Reference(id=str(uuid4()), kind="link", name="Chair", url="https://example.com/chair")
    project = store.change(project.id, 1, {"references": [reference.model_dump()]})
    run = service.create(project.id, project.revision, "reconstruct", "Restore", execution_mode="online")

    async def read(url):
        assert url == reference.url
        return {"name": "Chair", "text": "A chair made of straight wooden boards, seat width 400 mm."}

    monkeypatch.setattr(online_runs, "read_reference_link", read)
    provider = FakeProvider({"summary": "Candidate", "patch": candidate()})

    async def scenario():
        online_runs.start_online_run(service, run, provider)
        return await drain(service, run)

    assert asyncio.run(scenario())["status"] == "ready"
    assert "seat width 400 mm" in provider.calls[0][0]["text"]
    assert store.load(project.id).references[0].text == ""
    assert store.load(project.id).revision == project.revision
    evidence = json.loads((store.directory(project.id) / "design-run-evidence" / (run["id"] + ".json")).read_text(encoding="utf-8"))
    assert evidence["references"][0]["status"] == "read"


def test_unreadable_link_fails_before_provider(environment, monkeypatch):
    store, project, service = environment
    reference = Reference(id=str(uuid4()), kind="link", name="Chair", url="https://example.com/chair")
    project = store.change(project.id, 1, {"references": [reference.model_dump()]})
    run = service.create(project.id, project.revision, "reconstruct", "Restore", execution_mode="online")

    async def read(url):
        raise online_runs.ReferenceReadError("Private network SECRET_TOKEN")

    monkeypatch.setattr(online_runs, "read_reference_link", read)
    provider = FakeProvider()

    async def scenario():
        online_runs.start_online_run(service, run, provider)
        return await drain(service, run)

    result = asyncio.run(scenario())
    assert result["error"] == "evidence_unavailable"
    assert "SECRET_TOKEN" not in json.dumps(result)
    assert provider.calls == []


def test_local_images_and_selected_pdf_pages_are_sent_as_real_bytes(environment, monkeypatch):
    store, project, service = environment
    image = Reference(id=str(uuid4()), kind="image", name="Photo", url="/local/photo")
    document = Reference(id=str(uuid4()), kind="document", name="Drawing", url="/local/drawing")
    project = store.change(project.id, 1, {"references": [image.model_dump(), document.model_dump()]})
    raw = b"\x89PNG\r\n\x1a\nimage-evidence"
    path = store.directory(project.id) / "references" / image.id
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    monkeypatch.setattr(online_runs, "render_pdf_page", lambda *args: raw + b"-pdf")
    context = {"project": project.model_dump(mode="json"), "run": {"intent": "reconstruct", "text": "Restore"},
               "references": [{**image.model_dump(), "status": "available"},
                              {**document.model_dump(), "status": "read", "pages": [{"page": 2, "text": "Drawing"}]}],
               "contract": {}, "instructions": "Evidence only"}
    content = online_runs.build_online_content(service, context)
    urls = [item["image_url"]["url"] for item in content if item["type"] == "image_url"]
    assert len(urls) == 2
    assert base64.b64decode(urls[0].split(",", 1)[1]) == raw
    assert base64.b64decode(urls[1].split(",", 1)[1]) == raw + b"-pdf"
    assert all(url.startswith("data:image/png;base64,") for url in urls)
    context["references"][1]["omitted_page_count"] = 2
    with pytest.raises(online_runs.EvidenceUnavailable, match="6 页"):
        online_runs.build_online_content(service, context)
    context["references"][1]["omitted_page_count"] = 0
    monkeypatch.setattr(online_runs, "MAX_IMAGES", 1)
    with pytest.raises(online_runs.EvidenceUnavailable, match="预算"):
        online_runs.build_online_content(service, context)
