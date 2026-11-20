"""Revision-bound fabrication artifacts, derived only from an accepted design."""
from __future__ import annotations

import csv
import base64
import html
import io
import json
import os
from pathlib import Path
import tempfile
import zipfile
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.workbench import api
from app.workbench.engine import build_checks, build_package
from app.workbench.models import now

router = APIRouter(prefix="/api/workbench")


class ExportRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    visuals: dict[str, str] = Field(default_factory=dict, max_length=2)


def visual_images(values: dict[str, str]) -> dict[str, bytes]:
    """Only small, decoded PNG pixels from the accepted viewport; no remote URLs."""
    from PIL import Image
    images = {}
    for name, data in values.items():
        if name not in {'assembled', 'exploded'} or len(data) > 4_000_000 or not data.startswith('data:image/png;base64,'):
            raise HTTPException(422, '模型截图需要使用不超过 3 MB 的 PNG。')
        try:
            raw = base64.b64decode(data.split(',', 1)[1], validate=True)
            with Image.open(io.BytesIO(raw)) as picture:
                if picture.format != 'PNG' or not (1 <= picture.width <= 3000 and 1 <= picture.height <= 3000):
                    raise ValueError('image dimensions')
                picture.load()
                normalized = io.BytesIO()
                picture.convert('RGB').save(normalized, format='PNG')
                images[name] = normalized.getvalue()
        except Exception:
            raise HTTPException(422, '模型截图无法读取，请重新生成。') from None
    return images


def csv_bytes(headers: list[str], rows: list[list]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(headers)
    for row in rows:
        # Spreadsheet applications must not execute names supplied in references.
        writer.writerow(["'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else round(value, 3) if isinstance(value, float) else value for value in row])
    return stream.getvalue().encode("utf-8-sig")


def package_html(project: dict, package: dict, images: dict[str, bytes] | None = None) -> str:
    esc = lambda value: html.escape(str(value if value is not None else ""))
    def table(headers, rows):
        return '<table><thead><tr>' + ''.join('<th>'+esc(h)+'</th>' for h in headers) + '</tr></thead><tbody>' + ''.join('<tr>'+''.join('<td>'+esc(c)+'</td>' for c in row)+'</tr>' for row in rows) + '</tbody></table>'
    cuts = package.get("cut_list", [])
    hardware = package.get("hardware", [])
    procurement = table(['零件', '材料', '毛坯尺寸 mm', '数量'], [[p['name'], p.get('material_name'), ' × '.join(f'{value:.3f}'.rstrip('0').rstrip('.') for value in p['stock_size_mm']), p['quantity']] for p in cuts])
    hardware_table = table(['五金', '规格', '数量'], [[h['name'],h['spec'],h['quantity']] for h in hardware])
    assembly = ''.join('<li><strong>'+esc(step.get('name') or step.get('joint_id'))+'</strong><p>'+esc(step.get('instruction'))+'</p></li>' for step in package.get('assembly_steps', []))
    drawing_pages = ''.join('<section class="drawing"><div class="sheet-label">'+esc(project['name'])+' · v'+str(project['revision'])+' · '+esc(d.get('id'))+'</div>'+d['svg']+'</section>' for d in package.get('drawings', []))
    overview = ''.join('<figure><img alt="'+label+'" src="data:image/png;base64,'+base64.b64encode(images[name]).decode('ascii')+'"><figcaption>'+label+' · v'+str(project['revision'])+'</figcaption></figure>' for name,label in [('assembled','整椅参考'),('exploded','板件装配关系')] if name in (images or {}))
    return '''<!doctype html><html lang="zh"><meta charset="utf-8"><style>
@page { size:A3 landscape; margin:10mm; }
* { box-sizing:border-box; } body { margin:0; color:#26332d; font:12px "Microsoft YaHei","Noto Sans CJK SC",sans-serif; }
h1 { font-size:25px; } h2 { font-size:17px; margin:18px 0 8px; } p,li { line-height:1.6; } table { width:100%; border-collapse:collapse; margin:8px 0 18px; }
th,td { padding:6px 9px; border:1px solid #ccd3cb; text-align:left; } th { background:#eef1e9; } tr { break-inside:avoid; }
.drawing { break-before:page; width:397mm; height:277mm; overflow:hidden; position:relative; }
.drawing>svg { display:block; width:100%; height:calc(100% - 5mm); object-fit:contain; } .sheet-label { height:5mm; font-size:9px; color:#657064; }
.note { color:#586457; } .assembly { break-before:page; } .overview { display:flex; gap:8mm; break-after:page; } figure { margin:0; width:48%; } figure img { width:100%; height:205mm; object-fit:contain; } figcaption { text-align:center; } </style><body>''' + '<h1>'+esc(project['name'])+' · 加工包 v'+str(project['revision'])+'</h1><p>项目 '+esc(project['id'])+'</p>'+('<section class="overview">'+overview+'</section>' if overview else '')+'<h2>我买什么</h2>'+procurement+hardware_table+'<p class="note">板件表列出各零件毛坯外接尺寸和数量，尚未做整板排版；采购整板数量及锯缝余量由加工方结合板材规格确定。</p><h2>交给加工店什么</h2><p>后附零件与连接图纸，含简单平面斜切和孔位。以标注数值加工，不按屏幕或打印尺寸量取。</p><p class="note">'+esc('检查未覆盖：'+'；'.join(package.get('coverage', {}).get('not_checked', [])))+'</p><section class="assembly"><h2>我怎么装</h2><ol>'+assembly+'</ol></section>'+drawing_pages+'</body></html>'


async def render_pdf(document: str) -> bytes:
    from playwright.async_api import async_playwright
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page(java_script_enabled=False)
            await page.route("**/*", lambda route: route.continue_() if route.request.url.startswith('data:image/png;base64,') else route.abort())
            await page.set_content(document, wait_until="load")
            await page.evaluate("document.fonts.ready")
            return await page.pdf(prefer_css_page_size=True, print_background=True, scale=1)
        finally:
            await browser.close()


def stock_dimensions(cut: dict) -> list:
    dimensions = cut.get('stock_dimensions_mm')
    return ([dimensions['width_mm'], dimensions['thickness_mm'], dimensions['length_mm']]
            if dimensions else cut['stock_size_mm'])


def archive_bytes(project: dict, package: dict, pdf: bytes, document: str, images: dict[str, bytes] | None = None) -> bytes:
    output = io.BytesIO()
    cuts = package.get('cut_list', [])
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('model/design.json', json.dumps(project, ensure_ascii=False, indent=2))
        archive.writestr('package.json', json.dumps(package, ensure_ascii=False, indent=2))
        archive.writestr('drawings.pdf', pdf)
        archive.writestr('print.html', document)
        archive.writestr('cut-list.csv', csv_bytes(['零件编号','名称','材料','宽mm','厚mm','长mm','数量'], [[c['part_id'],c['name'],c.get('material_name'),*stock_dimensions(c),c['quantity']] for c in cuts]))
        archive.writestr('purchase.csv', csv_bytes(['毛坯编号','材料','宽mm','厚mm','长mm','数量','说明'], [[c['part_id'],c.get('material_name'),*stock_dimensions(c),c['quantity'],'按零件毛坯采购，未做整板排版及锯缝余量'] for c in cuts]))
        archive.writestr('hardware.csv', csv_bytes(['名称','规格','数量'], [[h['name'],h['spec'],h['quantity']] for h in package.get('hardware', [])]))
        archive.writestr('assembly.txt', '\n\n'.join(f"{i}. {s.get('name') or s.get('joint_id')}\n{s.get('instruction', '')}" for i,s in enumerate(package.get('assembly_steps', []),1)))
        for name, image in (images or {}).items():
            archive.writestr('views/'+name+'.png', image)
        for index, drawing in enumerate(package.get('drawings', []), 1):
            archive.writestr(f"drawings/{index:03d}.svg", drawing['svg'])
        archive.writestr('README.txt', f"Junior 加工包 · v{project['revision']}\n模型、图纸与清单来自同一个版本。model/design.json 为可重新导入的模型数据。\n图纸以标注尺寸为准。采购表按毛坯逐件列出，不是整板排版优化结果。\n检查范围见 package.json 的 coverage；承载、稳定性及实际工艺需要实物核实。\n")
    return output.getvalue()


def atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(handle, 'wb') as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def export_dir(project_id: UUID, revision: int) -> Path:
    if revision < 1:
        raise HTTPException(422, '无效版本')
    return api.workbench_store.directory(str(project_id)) / 'exports' / str(revision)


@router.post('/projects/{project_id}/exports')
async def create_export(project_id: UUID, body: ExportRequest):
    images = visual_images(body.visuals)
    with api.workbench_store.lock:
        project = api.load(project_id)
        if project.revision != body.expected_revision:
            raise HTTPException(409, '设计已更新，请按当前版本重新生成加工包。')
        snapshot = project.model_dump(mode='json')
        issues = build_checks(snapshot)
        blockers = [issue for issue in issues if issue['severity'] == 'blocker']
        from app.workbench.review import review_blockers
        blockers.extend(review_blockers(project))
        if blockers:
            raise HTTPException(409, {'message':'先解决这些问题，再生成加工包。','checks':blockers})
        directory = export_dir(project_id, project.revision)
        manifest = directory / 'manifest.json'
        if manifest.exists():
            return json.loads(manifest.read_text(encoding='utf-8'))
    package = build_package({**snapshot, 'export_revision': project.revision})
    package['status'] = 'ready'
    document = package_html(snapshot, package, images)
    try:
        pdf = await render_pdf(document)
    except Exception as exc:
        raise HTTPException(503, 'PDF 生成失败，设计已保留。请确认 Chromium 打印组件已安装后重试。') from exc
    archive = archive_bytes(snapshot, package, pdf, document, images)
    prefix = f'/api/workbench/projects/{project_id}/exports/{project.revision}'
    record = {'project_id':str(project_id), 'revision':project.revision, 'status':'ready', 'created_at':now(),
              'download_url':prefix+'/download', 'pdf_url':prefix+'/pdf', 'package_snapshot':package}
    # Manifest is the final commit marker. No design revision is changed by exporting.
    with api.workbench_store.lock:
        if manifest.exists():
            return json.loads(manifest.read_text(encoding='utf-8'))
        atomic_bytes(directory / 'drawings.pdf', pdf)
        atomic_bytes(directory / 'package.zip', archive)
        api.workbench_store.atomic_json(manifest, record)
    return record


@router.get('/projects/{project_id}/exports')
def list_exports(project_id: UUID):
    project = api.load(project_id)
    records = []
    for path in (api.workbench_store.directory(str(project_id)) / 'exports').glob('*/manifest.json'):
        record = json.loads(path.read_text(encoding='utf-8'))
        record.pop('package_snapshot', None)
        record['current'] = record['revision'] == project.revision
        records.append(record)
    return {'exports':sorted(records, key=lambda item:item['revision'], reverse=True)}


def artifact(project_id: UUID, revision: int, name: str, media: str):
    api.load(project_id)
    directory = export_dir(project_id, revision)
    if not (directory / 'manifest.json').exists() or not (directory / name).exists():
        raise HTTPException(404, '这个版本尚未生成加工包。')
    return FileResponse(directory / name, media_type=media, filename=f'junior-{project_id}-v{revision}'+Path(name).suffix)


@router.get('/projects/{project_id}/exports/{revision}/download')
def download_export(project_id: UUID, revision: int):
    return artifact(project_id, revision, 'package.zip', 'application/zip')


@router.get('/projects/{project_id}/exports/{revision}/pdf')
def download_pdf(project_id: UUID, revision: int):
    return artifact(project_id, revision, 'drawings.pdf', 'application/pdf')
