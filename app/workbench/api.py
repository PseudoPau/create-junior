"""Independent furniture workbench API."""
from __future__ import annotations
import io
import os
import json
import zipfile
from pathlib import Path
from uuid import UUID, uuid4
from fastapi import APIRouter, HTTPException, Request, Query, Body
from fastapi.responses import FileResponse, Response
from pydantic import ValidationError
from app.workbench.models import (
    Project, CreateProject, UpdateProject, ConfirmProject, AcceptProposal, Command, Restore,
    EDITABLE_FIELDS, PreparationRequest, Reference, ReferenceInput, now
)
from app.workbench.store import WorkbenchStore, RevisionConflict
from app.workbench.ai import propose, image_type
from app.workbench.reference_links import read_reference_link, ReferenceReadError
from app.workbench.proposals import ImportProposal, build_proposal
from app.workbench.engine import build_checks, build_package, check_coverage
from app.workbench.commands import Interaction, dimension_command, interaction_record, append_record, mark_accepted, mark_proposal_records, history
from app.workbench.module_fit import FitRequest, RevisionRequest, fit_preview

router = APIRouter(prefix="/api/workbench")
workbench_store = WorkbenchStore()

def load(project_id: UUID) -> Project:
    try:
        return workbench_store.load(str(project_id))
    except FileNotFoundError:
        raise HTTPException(404, "找不到项目")

def change(project_id: UUID, expected: int, patch: dict, confirm=False, accepted_joint_ids=None) -> Project:
    try:
        return workbench_store.change(str(project_id), expected, patch, confirm=confirm,
                                      accepted_joint_ids=accepted_joint_ids)
    except RevisionConflict as exc:
        raise HTTPException(409, str(exc))
    except FileNotFoundError:
        raise HTTPException(404, "找不到项目或版本")
    except (ValidationError, ValueError) as exc:
        raise HTTPException(422, str(exc))

def checked_patch(patch: dict):
    extra = set(patch) - EDITABLE_FIELDS
    if extra:
        raise HTTPException(422, "不可修改的字段：" + ", ".join(sorted(extra)))

@router.get("/projects")
def projects():
    return workbench_store.list_projects()

@router.post("/projects", response_model=Project)
def create_project(body: CreateProject):
    with workbench_store.lock:
        return workbench_store.save(Project(name=body.name))

@router.get("/projects/{project_id}", response_model=Project)
def get_project(project_id: UUID):
    return load(project_id)

@router.put("/projects/{project_id}", response_model=Project)
def update_project(project_id: UUID, body: UpdateProject):
    checked_patch(body.patch)
    return change(project_id, body.expected_revision, body.patch)


def guarded_fit(project_id: UUID, module_id: str, body: FitRequest):
    project = load(project_id)
    if project.revision != body.expected_revision:
        raise HTTPException(409, "项目已被修改，请刷新后再提交")
    try:
        return fit_preview(project, module_id, body.key, body.value)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(422, str(exc))


@router.post("/projects/{project_id}/modules/{module_id}/fit-preview")
def preview_module_fit(project_id: UUID, module_id: str, body: FitRequest):
    with workbench_store.lock:
        return guarded_fit(project_id, module_id, body)


@router.post("/projects/{project_id}/modules/{module_id}/fit-apply", response_model=Project)
def apply_module_fit(project_id: UUID, module_id: str, body: FitRequest):
    with workbench_store.lock:
        result = guarded_fit(project_id, module_id, body)
        return change(project_id, body.expected_revision, result['patch'])


@router.post("/projects/{project_id}/joints/{joint_id}/accept", response_model=Project)
def accept_joint(project_id: UUID, joint_id: str, body: RevisionRequest):
    with workbench_store.lock:
        project = load(project_id)
        if project.revision != body.expected_revision:
            raise HTTPException(409, "项目已被修改，请刷新后再提交")
        joint = next((item for item in project.joints if item.id == joint_id), None)
        if joint is None:
            raise HTTPException(404, "找不到这个连接")
        ids = set(joint.part_ids)
        failures = [issue for issue in build_checks(project.model_dump(mode='json'))
                    if issue['severity'] == 'blocker' and issue['code'] != 'joint_unconfirmed'
                    and (not issue.get('part_ids') or ids.intersection(issue['part_ids']))]
        if failures:
            raise HTTPException(422, '此连接还不能采用：' + '；'.join(issue['message'] for issue in failures[:3]))
        return change(project_id, body.expected_revision, {}, accepted_joint_ids={joint_id})

@router.post("/projects/{project_id}/references/item", response_model=Project)
def add_reference_item(project_id: UUID, body: ReferenceInput):
    with workbench_store.lock:
        project = load(project_id)
        if project.revision != body.expected_revision:
            raise HTTPException(409, "项目已变化，请刷新后添加资料")
        if len(project.references) >= 20:
            raise HTTPException(422, "每个项目最多保存 20 条参考资料")
        name = body.name.strip() or ("参考链接" if body.kind == "link" else "参考说明")
        try:
            ref = Reference(id=str(uuid4()), kind=body.kind, name=name,
                            url=body.url, text=body.text)
        except ValidationError as exc:
            raise HTTPException(422, exc.errors()[0]["msg"])
        references = [item.model_dump() for item in project.references]
        references.append(ref.model_dump())
        return change(project_id, project.revision, {"references": references})


@router.post("/projects/{project_id}/references/{reference_id}/resolve", response_model=Project)
async def resolve_reference(project_id: UUID, reference_id: UUID,
                            expected_revision: int = Body(embed=True, ge=1)):
    project = load(project_id)
    if project.revision != expected_revision:
        raise HTTPException(409, "项目已变化，请刷新后读取链接")
    ref = next((item for item in project.references if item.id == str(reference_id)), None)
    if ref is None or ref.kind != "link":
        raise HTTPException(404, "找不到参考链接")
    try:
        result = await read_reference_link(ref.url)
    except ReferenceReadError as exc:
        raise HTTPException(422, str(exc)) from None
    with workbench_store.lock:
        current = load(project_id)
        if current.revision != expected_revision:
            raise HTTPException(409, "读取期间项目已变化，请刷新后重试")
        references = [item.model_dump() for item in current.references]
        for item in references:
            if item["id"] == str(reference_id):
                item.update(result)
                break
        return change(project_id, expected_revision, {"references": references})


@router.post("/projects/{project_id}/references", response_model=Project)
async def upload(project_id: UUID, request: Request, filename: str = Query(default="参考文件", max_length=160)):
    load(project_id)
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(413, "单个参考文件最多 10 MB")
    is_pdf = data.startswith(b"%PDF-")
    kind = "document" if is_pdf else "image"
    if not is_pdf and not image_type(data):
        raise HTTPException(415, "请使用 PNG、JPEG、WebP 图片或 PDF 图纸")
    with workbench_store.lock:
        project = load(project_id)
        if len(project.references) >= 20:
            raise HTTPException(422, "每个项目最多保存 20 条参考资料")
        if kind == "image" and sum(ref.kind == "image" for ref in project.references) >= 8:
            raise HTTPException(422, "每个项目最多保存 8 张参考图片")
        ref_id = str(uuid4())
        directory = workbench_store.directory(str(project_id)) / "references"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / ref_id
        target.write_bytes(data)
        references = [ref.model_dump() for ref in project.references]
        references.append({"id": ref_id, "kind": kind, "name": Path(filename).name,
                           "url": f"/api/workbench/projects/{project_id}/references/{ref_id}"})
        try:
            return change(project_id, project.revision, {"references": references})
        except Exception:
            target.unlink(missing_ok=True)
            raise

@router.get("/projects/{project_id}/references/{reference_id}")
def reference(project_id: UUID, reference_id: UUID):
    project = load(project_id)
    ref = next((r for r in project.references if r.id == str(reference_id)), None)
    if ref is None or ref.kind not in {"image", "document"}:
        raise HTTPException(404, "找不到参考文件")
    path = workbench_store.directory(str(project_id)) / "references" / str(reference_id)
    if not path.exists():
        raise HTTPException(404, "参考文件缺失")
    media_type = "application/pdf" if ref.kind == "document" else image_type(path.read_bytes())
    return FileResponse(path, media_type=media_type, filename=ref.name,
                        content_disposition_type="inline")

@router.get("/ai/status")
def ai_status():
    mode = os.getenv("CREATE_JUNIOR_AI_PROVIDER", "openai_compatible").strip().lower()
    fields = {name: bool(os.getenv("CREATE_JUNIOR_AI_" + name, "").strip())
              for name in ("BASE_URL", "API_KEY", "MODEL")}
    ready = mode == "prototype" or (mode in {"openai", "openai_compatible"} and all(fields.values()))
    return {"mode": mode, "ready": ready, "session_available": True,
            "configured": fields, "model": os.getenv("CREATE_JUNIOR_AI_MODEL", "") if ready else "",
            "label": "本地原型生成" if mode == "prototype" else "在线 AI" if ready else "会话协作" if mode == "session" else "AI 未连接"}


@router.post("/projects/{project_id}/analyze")
async def analyze(project_id: UUID, expected_revision: int | None = Body(default=None, embed=True)):
    project = load(project_id)
    if expected_revision is not None and expected_revision != project.revision:
        raise HTTPException(409, "参考已变化，请刷新后重新生成")
    if os.getenv("CREATE_JUNIOR_AI_PROVIDER", "").strip().lower() == "session":
        if not project.references:
            raise HTTPException(422, "请先添加参考资料")
        record = request_preparation(project_id, PreparationRequest(
            expected_revision=project.revision, stage="reference",
            text="根据当前参考拟定可编辑家具模型，区分原物事实、改制决定和未知信息。"))
        return {"status": "handoff", "request_id": record["id"],
                "base_revision": project.revision, "summary": "已提交给当前会话；网页不会自动唤起聊天。"}
    proposal = await propose(workbench_store, project)
    with workbench_store.lock:
        if load(project_id).revision != project.revision:
            raise HTTPException(409, "生成期间项目已变化，结果未应用，请重新生成")
        workbench_store.save_proposal(str(project_id), proposal)
    return proposal


@router.post("/demos/cafe-chair")
def cafe_demo():
    from app.workbench.demo import cafe_candidate
    with workbench_store.lock:
        project = workbench_store.save(Project(name="CAFE CHAIR · 样例体验", references=[Reference(id=str(uuid4()), kind="note", name="内置 CAFE CHAIR 样例", text="明确加载现成样例以演示编辑和加工资料流程，非当前参考的自动识别结果。")]))
        proposal = cafe_candidate(project)
        workbench_store.save_proposal(project.id, proposal)
        return {"project": project, "proposal": proposal}


@router.post("/projects/{project_id}/command")
async def command(project_id: UUID, body: Command):
    project = load(project_id)
    if project.revision != body.expected_revision:
        raise HTTPException(409, "项目已变化，请刷新后重试")
    proposal = await propose(workbench_store, project, body.text)
    workbench_store.save_proposal(str(project_id), proposal)
    return proposal

@router.get("/projects/{project_id}/proposal")
def get_proposal(project_id: UUID):
    load(project_id)
    try:
        return workbench_store.proposal(str(project_id))
    except FileNotFoundError:
        raise HTTPException(404, "暂无候选")

@router.post("/projects/{project_id}/proposal/import")
async def import_proposal(project_id: UUID, request: Request, request_id: UUID | None = Query(default=None)):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 2 * 1024 * 1024:
            raise HTTPException(413, "候选 JSON 最多 2 MB")
    try:
        body = ImportProposal.model_validate_json(bytes(raw))
    except ValidationError:
        raise HTTPException(422, "候选需要 expected_revision、summary 和 patch；请检查 JSON 字段与类型")
    with workbench_store.lock:
        project = load(project_id)
        if body.expected_revision != project.revision:
            raise HTTPException(409, "候选基于旧版本，请按当前设计重新生成")
        if request_id is not None:
            pending_path = workbench_store.directory(project_id) / "preparation" / "request.json"
            pending = json.loads(pending_path.read_text(encoding="utf-8")) if pending_path.exists() else None
            if (pending is None or pending.get("id") != str(request_id)
                    or pending.get("status") != "pending"
                    or pending.get("base_revision") != project.revision):
                raise HTTPException(409, "协作请求已变化，请按当前请求重新生成候选")
        try:
            proposal = build_proposal(project, body.summary, body.patch, purpose=body.purpose)
        except ValidationError as exc:
            locations = [".".join(str(part) for part in error["loc"]) for error in exc.errors()]
            raise HTTPException(422, "候选字段不符合设计契约：" + "、".join(locations[:10]))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        proposal["source"] = "local_import"
        if request_id is not None:
            proposal["request_id"] = str(request_id)
        workbench_store.save_proposal(str(project_id), proposal)
        return proposal


@router.post("/projects/{project_id}/proposal/dismiss")
def dismiss(project_id: UUID, body: AcceptProposal):
    with workbench_store.lock:
        project = load(project_id)
        if body.expected_revision != project.revision:
            raise HTTPException(409, "项目已变化，请刷新后取消候选")
        try:
            proposal = workbench_store.proposal(str(project_id), body.proposal_id)
            latest = workbench_store.proposal(str(project_id))
        except (FileNotFoundError, ValueError):
            raise HTTPException(404, "找不到候选")
        if proposal["id"] != latest["id"] or proposal["base_revision"] != project.revision:
            raise HTTPException(409, "候选已被替换或基于旧版本，请刷新")
        if proposal["status"] not in {"ready", "cancelled"}:
            raise HTTPException(409, "这个候选无法取消")
        proposal.update(status="cancelled", cancelled_at=proposal.get("cancelled_at") or now())
        workbench_store.save_proposal(str(project_id), proposal)
        mark_proposal_records(workbench_store, project_id, proposal["id"], status="cancelled")
        from app.workbench.design_runs import DesignRuns
        DesignRuns(workbench_store).mark_result(str(project_id), proposal['id'], status='dismissed')
        if proposal.get("request_id"):
            directory = workbench_store.directory(project_id) / "preparation"
            request_path = directory / "requests" / (str(UUID(proposal["request_id"])) + ".json")
            if request_path.exists():
                request = json.loads(request_path.read_text(encoding="utf-8"))
                if (request.get("id") == proposal["request_id"]
                        and request.get("base_revision") == proposal["base_revision"]
                        and request.get("status") == "pending"):
                    request.update(last_declined_proposal_id=proposal["id"],
                                   declined_at=proposal["cancelled_at"])
                    workbench_store.atomic_json(request_path, request)
                    current_path = directory / "request.json"
                    current = json.loads(current_path.read_text(encoding="utf-8")) if current_path.exists() else None
                    if current and current.get("id") == request["id"]:
                        workbench_store.atomic_json(current_path, request)
        return {"proposal_id": proposal["id"], "status": "cancelled", "revision": project.revision}


@router.post("/projects/{project_id}/proposal/accept", response_model=Project)
def accept(project_id: UUID, body: AcceptProposal):
    with workbench_store.lock:
        project = load(project_id)
        try:
            proposal = workbench_store.proposal(str(project_id), body.proposal_id)
        except (FileNotFoundError, ValueError):
            raise HTTPException(404, "找不到候选")
        if proposal["status"] != "ready":
            raise HTTPException(409, "候选尚不可应用")
        if proposal["base_revision"] != project.revision or body.expected_revision != project.revision:
            raise HTTPException(409, "候选基于旧版本，请重新生成")
        checked_patch(proposal["patch"])
        accepted_ids = None
        if project.review_state is None and (body.accept_connections or not project.parts):
            candidate = Project.model_validate({**project.model_dump(mode="json"), **proposal["patch"]})
            checks = build_checks(candidate.model_dump(mode="json"))
            # Continue adopts concrete default methods, not unknown or invalid joints.
            # Geometry remains independently checked for every preview and export.
            accepted_ids = {
                joint.id for joint in candidate.joints
                if joint.kind in {"screw", "dowel"} and joint.assembly_note.strip()
                and joint.feature_ids and joint.hardware
                and not any(issue['severity'] == 'blocker'
                            and issue['code'] != 'joint_unconfirmed'
                            and set(issue.get('part_ids', [])).intersection(joint.part_ids)
                            for issue in checks)
            }
        updated = change(project_id, body.expected_revision, proposal["patch"],
                         accepted_joint_ids=accepted_ids)
        from app.workbench.design_runs import DesignRuns
        DesignRuns(workbench_store).mark_result(str(project_id), proposal['id'],
                                              status='completed', result_revision=updated.revision)
        mark_accepted(workbench_store, project_id, proposal, updated.revision)
        request_path = workbench_store.directory(project_id) / "preparation" / "request.json"
        if request_path.exists():
            request = json.loads(request_path.read_text(encoding="utf-8"))
            if proposal_answers_request(proposal, request, project.revision):
                request.update(status="completed", proposal_id=proposal["id"],
                               result_revision=updated.revision, completed_at=now())
                workbench_store.atomic_json(request_path, request)
                workbench_store.atomic_json(request_path.parent / "requests" / (request["id"] + ".json"), request)
        return updated

def preparation_conditions(project: Project) -> tuple[dict, list[dict]]:
    conditions = {
        "fabrication_mode": project.fabrication_mode,
        "requirements": project.requirements.model_dump(mode="json"),
        "scale": project.scale.model_dump(mode="json") if project.scale else None,
        "materials": {key: value.model_dump(mode="json") for key, value in project.materials.items()},
        "reference_count": len(project.references),
    }
    questions = []
    if project.fabrication_mode is None:
        questions.append({"key": "fabrication_mode", "label": "这次由谁加工零件？", "kind": "select",
                          "options": [{"value": "self", "label": "我自己加工"},
                                      {"value": "shop", "label": "加工店制件，我来装配"}]})
    return conditions, questions


def proposal_answers_request(proposal: dict, request: dict, revision: int) -> bool:
    """Only an explicitly linked candidate can answer a current collaboration request."""
    return (
        request.get("status") == "pending"
        and proposal.get("request_id") == request.get("id")
        and bool(request.get("id"))
        and proposal.get("status") == "ready"
        and proposal.get("base_revision") == request.get("base_revision") == revision
        and proposal.get("id") != request.get("previous_proposal_id")
    )


def preparation_request_stage(request: dict, project: Project) -> str:
    # Older requests keep their original document untouched; infer their phase
    # from the captured model rather than from later edits to the project.
    if request.get("stage"):
        return request["stage"]
    parts = request.get("project", {}).get("parts", project.parts)
    return "manufacturing" if parts else "reference"


def saved_preparation_request(project: Project) -> dict | None:
    path = workbench_store.directory(project.id) / "preparation" / "request.json"
    if not path.exists():
        return None
    request = json.loads(path.read_text(encoding="utf-8"))
    request["stage"] = preparation_request_stage(request, project)
    if request.get("status") in {"completed", "cancelled"}:
        return request
    if request["base_revision"] != project.revision:
        request["status"] = "stale"
    else:
        try:
            proposal = workbench_store.proposal(project.id)
            if proposal_answers_request(proposal, request, project.revision):
                request["status"] = "ready"
                request["proposal_id"] = proposal["id"]
        except FileNotFoundError:
            pass
    return request


@router.get("/projects/{project_id}/preparation")
def preparation(project_id: UUID):
    with workbench_store.lock:
        project = load(project_id)
        conditions, questions = preparation_conditions(project)
        return {"revision": project.revision, "conditions": conditions,
                "missing_questions": questions,
                "package_preview": build_package(project.model_dump(mode="json")),
                "request": saved_preparation_request(project)}


@router.post("/projects/{project_id}/preparation/request")
def request_preparation(project_id: UUID, body: PreparationRequest):
    # A local handoff record for the current Codex session, never an implicit model call.
    with workbench_store.lock:
        project = load(project_id)
        if body.expected_revision != project.revision:
            raise HTTPException(409, "设计条件已变化，请刷新后再整理方案")
        directory = workbench_store.directory(project.id)
        prior_path = directory / "preparation" / "request.json"
        prior = json.loads(prior_path.read_text(encoding="utf-8")) if prior_path.exists() else None
        # Repeated submission of the same current request is idempotent. Different
        # instructions create a new request and retain the existing input history.
        if (prior and prior.get("status") == "pending"
                and prior.get("base_revision") == project.revision
                and preparation_request_stage(prior, project) == body.stage
                and prior.get("text", "").strip() == body.text.strip()):
            return saved_preparation_request(project) or prior
        original = None
        for path in sorted((directory / "versions").glob("*.json"), key=lambda item: int(item.stem)):
            historical = Project.model_validate_json(path.read_text(encoding="utf-8"))
            if historical.parts:
                original = historical.model_dump(mode="json")
                break
        conditions, questions = preparation_conditions(project)
        # Free-text additions remain input evidence until the collaborating session
        # resolves them into a proposed design. A new blank request must not erase them.
        user_instructions = list(prior.get("user_instructions", [])) if prior else []
        if prior and not user_instructions and prior.get("text", "").strip():
            user_instructions.append({"text": prior["text"], "source_revision": prior["base_revision"],
                                      "request_id": prior["id"]})
        request_id = str(uuid4())
        if body.text.strip():
            user_instructions.append({"text": body.text, "source_revision": project.revision,
                                      "request_id": request_id})
        try:
            previous_proposal_id = workbench_store.proposal(project.id).get("id")
        except FileNotFoundError:
            previous_proposal_id = None
        record = {"id": request_id, "base_revision": project.revision, "status": "pending",
                  "stage": body.stage,
                  "created_at": now(), "text": body.text, "previous_proposal_id": previous_proposal_id,
                  "project": project.model_dump(mode="json"), "original_design": original,
                  "conditions": conditions, "missing_questions": questions,
                  "user_instructions": user_instructions,
                  "context": workbench_store.context(), "checks": build_checks(project.model_dump(mode="json")),
                  "instruction": "基于原始参考、当前设计及已给条件拟定加工方案；沿用已有答案，只询问无法推断的关键条件。user_instructions 按输入顺序保留补充原文，不是已经解析或确认的事实；冲突时说明并核对，不能静默覆盖。由 Codex 会话处理，本地程序不会自动调用该会话。"}
        workbench_store.atomic_json(directory / "preparation" / "requests" / (record["id"] + ".json"), record)
        workbench_store.atomic_json(directory / "preparation" / "request.json", record)
        return record


@router.post("/projects/{project_id}/interaction")
def interaction(project_id: UUID, body: Interaction):
    with workbench_store.lock:
        project = load(project_id)
        if body.expected_revision != project.revision:
            raise HTTPException(409, "项目已变化，请刷新后重新发送")
        if not body.text.strip():
            raise HTTPException(422, "请输入要做的调整")
        result = dimension_command(project, body.text, body.selected_part_id)
        if result is None:
            request = request_preparation(project_id, PreparationRequest(expected_revision=project.revision, text=body.text, stage=body.stage))
            reply = "已保存。回到当前聊天说“处理 Junior 请求”；方案返回后会出现在这里。"
            return {"kind": "handoff", "reply": reply, "request_id": request["id"]}
        if "patch" not in result:
            record = interaction_record(project, body.text, result["reply"], kind="reply", status="completed")
            append_record(workbench_store, project.id, record)
            return {"kind": "reply", "reply": result["reply"], "record": record}
        try:
            proposal = build_proposal(project, result["summary"], result["patch"])
        except (ValidationError, ValueError) as exc:
            raise HTTPException(422, str(exc))
        proposal["source"] = "local_command"
        workbench_store.save_proposal(project.id, proposal)
        record = interaction_record(project, body.text, result["summary"], kind="proposal", status="ready", proposal_id=proposal["id"], part_id=result["part_id"])
        append_record(workbench_store, project.id, record)
        return {"kind": "proposal", "reply": result["summary"], "proposal": proposal, "record": record}


@router.get("/projects/{project_id}/interaction/history")
def interaction_history(project_id: UUID):
    with workbench_store.lock:
        project = load(project_id)
        return {"revision": project.revision, "records": history(workbench_store, project)}


@router.get("/projects/{project_id}/checks")
def checks(project_id: UUID):
    project = load(project_id).model_dump(mode="json")
    return {"revision": project["revision"], "checks": build_checks(project), "coverage": check_coverage()}

@router.post("/projects/{project_id}/confirm", response_model=Project)
def confirm(project_id: UUID, body: ConfirmProject):
    with workbench_store.lock:
        project = load(project_id)
        if body.expected_revision != project.revision:
            raise HTTPException(409, "项目已变化，请刷新后核对")
        issues = build_checks(project.model_dump(mode="json"))
        blockers = [issue for issue in issues if issue["severity"] == "blocker"]
        from app.workbench.review import review_blockers
        blockers.extend(review_blockers(project))
        if blockers:
            raise HTTPException(409, {"message": "请先解决阻塞问题", "checks": blockers})
        if not body.acknowledged_limits:
            raise HTTPException(409, "请先阅读并确认检查覆盖范围")
        if project.confirmed_revision == project.revision:
            return project
        return change(project_id, body.expected_revision, {}, confirm=True)

@router.get("/projects/{project_id}/package")
def package(project_id: UUID):
    return build_package(load(project_id).model_dump(mode="json"))

@router.get("/projects/{project_id}/package/download")
def download(project_id: UUID, revision: int = Query(..., ge=1)):
    with workbench_store.lock:
        project = load(project_id)
        if project.revision != revision:
            raise HTTPException(409, "设计已变化，请重新核对要下载的版本")
        package = build_package(project.model_dump(mode="json"))
    if package["status"] != "ready":
        raise HTTPException(409, {"message": "只有已确认且无阻塞的设计可发布加工包", "checks": package["checks"]})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("design.json", project.model_dump_json(indent=2))
        archive.writestr("package.json", json.dumps(package, ensure_ascii=False, indent=2))
        archive.writestr("README.txt",
            "Junior 可核对设计包\n设计与检查绑定同一版本。\n先阅读 package.json 的 coverage、checks、assumptions。\n"
            "图纸为尺寸核对资料，不是数控刀路。未覆盖项目不能解释为通过；本包不是整椅安全认证。\n"
            "self 为自行加工，shop 为加工店制件后自行装配；生成设计包不扣减库存。\n")
        for index, drawing in enumerate(package.get("drawings", []), 1):
            # Drawing IDs derive from constrained part and joint IDs.
            archive.writestr(f"drawings/{index:03d}-{drawing['id']}.svg", drawing["svg"])
    return Response(buffer.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="junior-{project.id}-r{project.revision}.zip"'})

@router.get("/projects/{project_id}/versions")
def versions(project_id: UUID):
    load(project_id)
    return workbench_store.versions(str(project_id))

@router.post("/projects/{project_id}/restore/{revision}", response_model=Project)
def restore(project_id: UUID, revision: int, body: Restore):
    with workbench_store.lock:
        load(project_id)
        try:
            return workbench_store.restore(str(project_id), revision, body.expected_revision)
        except FileNotFoundError:
            raise HTTPException(404, "找不到该版本")
        except RevisionConflict as exc:
            raise HTTPException(409, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))

@router.get("/context")
def get_context():
    return workbench_store.context()

@router.put("/context")
async def update_context(request: Request):
    raw = await request.body()
    if len(raw) > 512 * 1024:
        raise HTTPException(413, "偏好和仓库记录过大")
    try:
        patch = json.loads(raw)
    except ValueError:
        raise HTTPException(422, "无效 JSON")
    if not isinstance(patch, dict) or set(patch) - {"preferences", "inventory", "expected_revision"}:
        raise HTTPException(422, "只允许保存 preferences 和 inventory")
    if "preferences" in patch and not isinstance(patch["preferences"], dict):
        raise HTTPException(422, "preferences 必须为对象")
    if "inventory" in patch and not isinstance(patch["inventory"], list):
        raise HTTPException(422, "inventory 必须为列表")
    with workbench_store.lock:
        previous = workbench_store.context()
        if patch.pop("expected_revision", None) != previous["revision"]:
            raise HTTPException(409, "偏好或仓库已被修改，请重新加载后保存")
        context = {**previous, **patch, "revision": previous["revision"] + 1}
        workbench_store.atomic_json(workbench_store.root / "context.json", context)
        return context
