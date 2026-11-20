"""Project-scoped evidence for a session agent; PDF pages are explicit, never silent."""
from __future__ import annotations
from io import BytesIO
from threading import RLock
from uuid import UUID
from app.workbench.models import Project
from app.workbench.store import WorkbenchStore

MAX_PDF_PAGES = 6
_PDF_LOCK = RLock()


def reference_path(store: WorkbenchStore, project: Project, reference_id: str, kind: str | None = None):
    reference_id = str(UUID(reference_id))
    ref = next((r for r in project.references if r.id == reference_id), None)
    if ref is None or (kind and ref.kind != kind) or ref.kind not in {"document", "image"}:
        raise FileNotFoundError("找不到项目关联的参考文件。")
    root = (store.directory(project.id) / "references").resolve()
    path = root / reference_id
    if not path.resolve().is_relative_to(root):
        raise ValueError("参考文件必须位于当前项目的资料目录内。")
    if not path.is_file():
        raise FileNotFoundError("参考文件缺失，请重新上传。")
    return path


def _pdfium():
    try:
        import pypdfium2
    except ImportError:
        raise ValueError("PDF 阅读组件尚未安装；请安装项目依赖后重试。") from None
    return pypdfium2


def reference_context(store: WorkbenchStore, project: Project, pages: list[int] | None = None) -> list[dict]:
    if pages is not None and (not pages or len(pages) > MAX_PDF_PAGES or any(p < 1 for p in pages)):
        raise ValueError("一次选择 1–6 个 PDF 页码，页码从 1 开始。")
    result = []
    for ref in project.references:
        item = ref.model_dump(mode="json")
        if ref.kind in {"link", "note"}:
            item["status"] = "read" if ref.text else "unread"
            if ref.kind == "link" and not ref.text:
                item["message"] = "网页尚未成功读取；不能把 URL 当作已经获取的内容。"
        elif ref.kind == "image":
            try:
                reference_path(store, project, ref.id, "image")
                item.update(status="available", image_url=ref.url)
            except (ValueError, FileNotFoundError) as exc:
                item.update(status="unavailable", message=str(exc))
        else:
            try:
                pdfium = _pdfium()
                path = reference_path(store, project, ref.id, "document")
                # PDFium is not thread-safe; serialize native calls across requests.
                with _PDF_LOCK, pdfium.PdfDocument(path) as doc:
                    selected = sorted(set(pages or range(1, min(len(doc), MAX_PDF_PAGES) + 1)))
                    item.update(page_count=len(doc), selected_pages=selected, pages=[], omitted_page_count=len(doc) - len(selected))
                    if any(p > len(doc) for p in selected):
                        raise ValueError(f"所选页码超出此 PDF 的 {len(doc)} 页范围。")
                    for number in selected:
                        page = doc[number - 1]
                        textpage = page.get_textpage()
                        try:
                            content = textpage.get_text_bounded()
                        finally:
                            textpage.close()
                        item["pages"].append({"page": number, "text": content[:12000], "text_truncated": len(content) > 12000,
                            "image_url": f"/api/workbench/projects/{project.id}/references/{ref.id}/pages/{number}"})
                    item["status"] = "read"
                    if item["omitted_page_count"]:
                        item["message"] = "仅处理所列页码；其他页面尚未读取，可通过 pages 参数选取。"
            except (ValueError, FileNotFoundError, RuntimeError) as exc:
                item.update(status="unavailable", message=str(exc))
        result.append(item)
    return result


def render_pdf_page(store: WorkbenchStore, project: Project, reference_id: str, page_number: int) -> bytes:
    pdfium = _pdfium()
    path = reference_path(store, project, reference_id, "document")
    with _PDF_LOCK, pdfium.PdfDocument(path) as doc:
        if not 1 <= page_number <= len(doc):
            raise ValueError("PDF 页码超出范围。")
        page = doc[page_number - 1]
        width, height = page.get_size()
        if width <= 0 or height <= 0:
            raise ValueError("PDF 页面尺寸无效。")
        scale = min(2, 1600 / max(width, height))
        bitmap = page.render(scale=scale)
        try:
            picture = bitmap.to_pil()
            output = BytesIO()
            picture.save(output, format="PNG")
            picture.close()
            return output.getvalue()
        finally:
            bitmap.close()
