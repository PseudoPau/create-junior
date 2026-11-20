"""Design task HTTP API for automatic online execution and explicit session handoff."""
from __future__ import annotations
import os
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import Field, ValidationError
from app.workbench.models import Record
from app.workbench.design_runs import DesignRuns, RunConflict
from app.workbench.store import RevisionConflict
from app.workbench.reference_context import render_pdf_page
from app.workbench.online_runs import start_online_run, cancel_online_run

router = APIRouter(prefix="/api/workbench")

class RunRevision(Record):
    expected_revision: int = Field(ge=1)

class CreateRun(RunRevision):
    intent: Literal["reconstruct", "modify", "repair"] = "reconstruct"
    text: str = Field(default="", max_length=4000)
    client_request_id: str | None = Field(default=None, min_length=1, max_length=128)
    requested_result_kind: Literal["design", "advice"] = "design"

class Worker(RunRevision):
    worker_id: str = Field(min_length=1, max_length=128)

class Preview(Worker):
    summary: str = Field(min_length=1, max_length=8000)
    patch: dict

class Finish(Worker):
    proposal_id: UUID

class Question(Worker):
    question: str = Field(min_length=1, max_length=2000)

class Failure(Worker):
    message: str = Field(min_length=1, max_length=2000)

class Answer(RunRevision):
    answer: str = Field(min_length=1, max_length=4000)

def service():
    # Resolve dynamically so the existing API and isolated test stores share one lock.
    from app.workbench.api import workbench_store
    return DesignRuns(workbench_store)

def invoke(method, *args, **kwargs):
    try:
        return method(*args, **kwargs)
    except FileNotFoundError:
        raise HTTPException(404, "找不到项目、任务或参考文件。") from None
    except (RevisionConflict, RunConflict) as exc:
        raise HTTPException(409, str(exc)) from None
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from None

@router.post("/projects/{project_id}/design-runs")
async def create_run(project_id: UUID, body: CreateRun):
    runner = service()
    mode = "session" if os.getenv("CREATE_JUNIOR_AI_PROVIDER", "openai_compatible").strip().lower() == "session" else "online"
    run = invoke(runner.create, str(project_id), **body.model_dump(), execution_mode=mode)
    return invoke(start_online_run, runner, run)

@router.get("/projects/{project_id}/design-runs")
def list_runs(project_id: UUID):
    return invoke(service().list, str(project_id))

@router.get("/projects/{project_id}/design-runs/{run_id}")
def get_run(project_id: UUID, run_id: UUID):
    return invoke(service().get, str(project_id), str(run_id))

@router.post("/projects/{project_id}/design-runs/{run_id}/claim")
def claim(project_id: UUID, run_id: UUID, body: Worker):
    return invoke(service().claim, str(project_id), str(run_id), **body.model_dump())

@router.post("/projects/{project_id}/design-runs/{run_id}/heartbeat")
def heartbeat(project_id: UUID, run_id: UUID, body: Worker):
    return invoke(service().heartbeat, str(project_id), str(run_id), **body.model_dump())

@router.get("/projects/{project_id}/design-runs/{run_id}/context")
def context(project_id: UUID, run_id: UUID, pages: str | None = Query(default=None, max_length=100)):
    try:
        selected = [int(number.strip()) for number in pages.split(",")] if pages else None
    except ValueError:
        raise HTTPException(422, "pages 使用逗号分隔的页码，如 1,2,4。") from None
    return invoke(service().context, str(project_id), str(run_id), selected)

@router.post("/projects/{project_id}/design-runs/{run_id}/preview")
async def preview(project_id: UUID, run_id: UUID, request: Request):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 2 * 1024 * 1024:
            raise HTTPException(413, "候选 JSON 最多 2 MB。")
    try:
        body = Preview.model_validate_json(bytes(raw))
    except ValidationError:
        raise HTTPException(422, "需要 expected_revision、worker_id、summary 和 patch。") from None
    return invoke(service().preview, str(project_id), str(run_id), **body.model_dump())

@router.post("/projects/{project_id}/design-runs/{run_id}/finish")
def finish(project_id: UUID, run_id: UUID, body: Finish):
    return invoke(service().finish, str(project_id), str(run_id), **body.model_dump(mode="json"))

@router.post("/projects/{project_id}/design-runs/{run_id}/question")
def question(project_id: UUID, run_id: UUID, body: Question):
    return invoke(service().question, str(project_id), str(run_id), **body.model_dump())

@router.post("/projects/{project_id}/design-runs/{run_id}/answer")
async def answer(project_id: UUID, run_id: UUID, body: Answer):
    runner = service()
    run = invoke(runner.answer, str(project_id), str(run_id), **body.model_dump())
    return invoke(start_online_run, runner, run)

@router.post("/projects/{project_id}/design-runs/{run_id}/cancel")
async def cancel(project_id: UUID, run_id: UUID, body: RunRevision):
    runner = service()
    run = invoke(runner.cancel, str(project_id), str(run_id), **body.model_dump())
    cancel_online_run(runner, str(project_id), str(run_id))
    return run

@router.post("/projects/{project_id}/design-runs/{run_id}/fail")
def fail(project_id: UUID, run_id: UUID, body: Failure):
    return invoke(service().fail, str(project_id), str(run_id), **body.model_dump())

@router.get("/projects/{project_id}/references/{reference_id}/pages/{page_number}")
def pdf_page(project_id: UUID, reference_id: UUID, page_number: int):
    runner = service()
    project = invoke(runner.store.load, str(project_id))
    image = invoke(render_pdf_page, runner.store, project, str(reference_id), page_number)
    return Response(image, media_type="image/png")
