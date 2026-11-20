"""Single-process online executor; only DesignRuns may publish a checked candidate."""
from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Any
from uuid import uuid4

import httpx

from app.workbench.ai import DesignerProvider, configured_designer, image_type
from app.workbench.design_runs import DesignRuns, MAX_ATTEMPTS, RunConflict
from app.workbench.models import Project
from app.workbench.reference_context import reference_path, render_pdf_page
from app.workbench.reference_links import read_reference_link, ReferenceReadError
from app.workbench.store import RevisionConflict

RUN_TIMEOUT_SECONDS = 360
POLL_SECONDS = 2
HEARTBEAT_SECONDS = 45
MAX_REFERENCES = 20
MAX_IMAGES = 12
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 12 * 1024 * 1024
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024

_tasks: dict[tuple[str, str, str], asyncio.Task] = {}


class EvidenceUnavailable(ValueError):
    """Safe, fixed user-facing evidence failure, never provider exception text."""


class RunStopped(Exception):
    pass


def _key(service: DesignRuns, project_id: str, run_id: str) -> tuple[str, str, str]:
    return str(service.store.root.resolve()), project_id, run_id


def _fail(service: DesignRuns, run: dict, worker_id: str, message: str, code: str) -> None:
    try:
        service.fail(run["project_id"], run["id"], run["base_revision"], worker_id, message, code=code)
    except (RunConflict, RevisionConflict, FileNotFoundError):
        # A user's cancellation or newer design always wins over a late result.
        pass


def build_online_content(service: DesignRuns, context: dict) -> list[dict[str, Any]]:
    """Resolve local evidence into bytes the remote vision provider can actually read."""
    project = Project.model_validate(context["project"])
    references = context["references"]
    if len(references) > MAX_REFERENCES:
        raise EvidenceUnavailable("参考资料超过本轮支持的 20 项，请减少资料后重试；本次没有省略资料继续生成。")
    run = context["run"]
    if not references and not project.parts and not run.get("text", "").strip():
        raise EvidenceUnavailable("请先提供参考图片、图纸、已读取的网页或设计说明。")
    for reference in references:
        if reference.get("status") in {"unavailable", "unread"}:
            raise EvidenceUnavailable("有参考资料尚未成功读取，请重新上传或补充可读取内容后重试。")
        if reference.get("omitted_page_count", 0):
            raise EvidenceUnavailable("PDF 超过本轮每份 6 页的阅读范围，请先拆分所需页面后重试；未读页面不会被视为已分析。")
        if any(page.get("text_truncated") for page in reference.get("pages", [])):
            raise EvidenceUnavailable("PDF 页面文字超过本轮阅读预算，请拆分或精简参考页面后重试。")
    text = json.dumps({
        "task": run.get("text", ""), "intent": run["intent"],
        "requested_result_kind": run.get("requested_result_kind", "design"),
        "answers": run.get("answers", []),
        "project": context["project"], "baseline_project": context.get("baseline_project"),
        "references": references, "contract": context["contract"],
        "instructions": context["instructions"],
        "response_contract": "返回 {summary, patch}；缺关键信息返回 {question}，一次只问一项。advice 任务只能修改现有 modules 的 suggestions 和 notes，其他字段及顺序保持不变。",
    }, ensure_ascii=False)
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise EvidenceUnavailable("项目和参考文字超过本轮处理预算，请减少参考后重试。")
    content = [{"type": "text", "text": text}]
    total_bytes = 0
    image_count = 0

    def append_image(raw: bytes, label: str) -> None:
        nonlocal total_bytes, image_count
        media = image_type(raw)
        if not media:
            raise EvidenceUnavailable("参考图片格式不支持，请改用 PNG、JPEG 或 WebP。")
        total_bytes += len(raw)
        image_count += 1
        if len(raw) > MAX_IMAGE_BYTES or total_bytes > MAX_TOTAL_IMAGE_BYTES or image_count > MAX_IMAGES:
            raise EvidenceUnavailable("图片超出本轮预算（最多 12 张、单张 4 MB、总计 12 MB），请减少或压缩参考后重试。")
        content.extend([
            {"type": "text", "text": label},
            {"type": "image_url", "image_url": {"url": f"data:{media};base64,{base64.b64encode(raw).decode('ascii')}"}},
        ])

    for reference in references:
        if reference["kind"] == "image":
            path = reference_path(service.store, project, reference["id"], "image")
            if path.stat().st_size > MAX_IMAGE_BYTES:
                raise EvidenceUnavailable("参考图片超过单张 4 MB 的处理预算，请压缩后重新上传。")
            append_image(path.read_bytes(), f"参考图片 ID：{reference['id']}")
        elif reference["kind"] == "document":
            for page in reference.get("pages", []):
                raw = render_pdf_page(service.store, project, reference["id"], page["page"])
                append_image(raw, f"参考 PDF ID：{reference['id']}，第 {page['page']} 页")
    return content


async def _generate(service: DesignRuns, run: dict, worker_id: str, provider: DesignerProvider) -> None:
    project_id, run_id, revision = run["project_id"], run["id"], run["base_revision"]
    context = await asyncio.to_thread(service.context, project_id, run_id)
    if len(context["references"]) > MAX_REFERENCES:
        raise EvidenceUnavailable("参考资料超过本轮支持的 20 项，请减少资料后重试。")
    for reference in context["references"]:
        if reference["kind"] == "link":
            if reference.get("status") == "unread":
                try:
                    read = await read_reference_link(reference["url"])
                except ReferenceReadError:
                    raise EvidenceUnavailable("参考网页未能成功读取，请补充图片、PDF 或网页正文后重试。") from None
                reference.update(name=read["name"], text=read["text"], status="read")
            reference["reading_scope"] = "网页正文摘录；未读取网页图片，不能从 URL 推断外观或不可见连接。"
    service.heartbeat(project_id, run_id, revision, worker_id)
    # Retain resolved evidence for diagnosis; preparation is not proof of model receipt.
    service.store.atomic_json(service.store.directory(project_id) / "design-run-evidence" / (run_id + ".json"), {
        "base_revision": revision, "status": "prepared", "references": context["references"],
    })
    base_content = await asyncio.to_thread(build_online_content, service, context)
    content = base_content
    for _ in range(MAX_ATTEMPTS - run["attempt"]):
        # Do not start another billable request if the prior input has become stale.
        service.heartbeat(project_id, run_id, revision, worker_id)
        payload = await provider.generate(content)
        service.heartbeat(project_id, run_id, revision, worker_id)
        if not isinstance(payload, dict):
            raise ValueError("response_contract")
        if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise ValueError("response_budget")
        if "question" in payload:
            question = payload["question"]
            if set(payload) != {"question"} or not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
                raise ValueError("question_contract")
            service.question(project_id, run_id, revision, worker_id, question.strip())
            return
        summary, patch = payload.get("summary"), payload.get("patch")
        if not isinstance(summary, str) or not 1 <= len(summary.strip()) <= 8000 or not isinstance(patch, dict):
            raise ValueError("response_contract")
        checked = service.preview(project_id, run_id, revision, worker_id, summary.strip(), patch)
        if checked["run"]["status"] == "failed":
            return
        if not checked["repairable_issues"]:
            service.finish(project_id, run_id, revision, worker_id, checked["proposal"]["id"])
            return
        # Retain one prior candidate and its diagnostics rather than unbounded history.
        content = [*base_content, {"type": "text", "text": json.dumps({
            "previous_candidate": {"summary": summary, "patch": patch},
            "repairable_issues": checked["repairable_issues"],
            "instruction": "修正这些问题并返回完整候选，patch 中数组是完整替换。",
        }, ensure_ascii=False)}]
    _fail(service, run, worker_id, "已达到三轮修正上限，请调整方案后重试。", "repair_limit")


async def _watch(service: DesignRuns, run: dict, worker_id: str) -> None:
    last_heartbeat = time.monotonic()
    while True:
        await asyncio.sleep(POLL_SECONDS)
        current = service.get(run["project_id"], run["id"])
        if current["status"] != "running" or current.get("worker_id") != worker_id:
            raise RunStopped()
        if time.monotonic() - last_heartbeat >= HEARTBEAT_SECONDS:
            service.heartbeat(run["project_id"], run["id"], run["base_revision"], worker_id)
            last_heartbeat = time.monotonic()


async def execute_online_run(service: DesignRuns, run: dict, worker_id: str, provider: DesignerProvider,
                             timeout_seconds: float = RUN_TIMEOUT_SECONDS) -> None:
    work = asyncio.create_task(_generate(service, run, worker_id, provider))
    watch = asyncio.create_task(_watch(service, run, worker_id))
    try:
        async with asyncio.timeout(timeout_seconds):
            finished, _ = await asyncio.wait({work, watch}, return_when=asyncio.FIRST_COMPLETED)
            # A successful finish also changes status; prefer the completed work.
            await (work if work in finished else watch)
    except (RunStopped, RunConflict, RevisionConflict):
        pass
    except TimeoutError:
        _fail(service, run, worker_id, "AI 处理超时，请稍后重试或减少参考资料。", "online_timeout")
    except asyncio.CancelledError:
        _fail(service, run, worker_id, "AI 处理已中断，可以重新提交。", "worker_interrupted")
        raise
    except EvidenceUnavailable as exc:
        _fail(service, run, worker_id, str(exc), "evidence_unavailable")
    except httpx.HTTPStatusError as exc:
        _fail(service, run, worker_id, f"AI 服务返回 HTTP {exc.response.status_code}，请检查通道配置后重试。", "provider_http_error")
    except httpx.HTTPError:
        _fail(service, run, worker_id, "AI 服务连接失败，请稍后重试。", "provider_connection_error")
    except (ValueError, TypeError, KeyError, IndexError):
        _fail(service, run, worker_id, "AI 返回内容不符合设计协议，请重试。", "provider_contract_error")
    except Exception:
        # Never expose provider exception bodies, URLs, API keys or local paths.
        _fail(service, run, worker_id, "AI 任务未能完成，请重试或检查服务状态。", "online_internal_error")
    finally:
        for task in (work, watch):
            if not task.done():
                task.cancel()
        await asyncio.gather(work, watch, return_exceptions=True)


def start_online_run(service: DesignRuns, run: dict, provider: DesignerProvider | None = None) -> dict:
    """Called on the event loop; claim before returning, so restarts cannot strand a queued job."""
    run = service.get(run["project_id"], run["id"])
    if run.get("execution_mode", "session") != "online" or run["status"] != "waiting_for_session":
        return run
    key = _key(service, run["project_id"], run["id"])
    provider = provider or configured_designer()
    worker_id = "online:" + str(uuid4())
    run = service.claim(run["project_id"], run["id"], run["base_revision"], worker_id, provider_name=provider.name)
    if provider.name in {"unavailable", "prototype"}:
        _fail(service, run, worker_id,
              "在线 AI 尚未连接。请配置服务端提供方、API 地址、密钥和视觉模型；样例模式不能分析参考。",
              "provider_unavailable")
        return service.get(run["project_id"], run["id"])
    task = asyncio.create_task(execute_online_run(service, run, worker_id, provider))
    _tasks[key] = task

    def completed(done: asyncio.Task) -> None:
        if _tasks.get(key) is done:
            _tasks.pop(key, None)
        # The executor catches failures; retrieving a cancellation is unnecessary.
        if not done.cancelled():
            done.exception()

    task.add_done_callback(completed)
    return run


def cancel_online_run(service: DesignRuns, project_id: str, run_id: str) -> None:
    task = _tasks.get(_key(service, project_id, run_id))
    if task is not None:
        task.cancel()
