"""Revision-bound fabrication artifacts, derived only from an accepted design."""
from __future__ import annotations

import csv
import base64
import html
import io
import json
import math
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
    budget = package.get("budget") or {}
    plan = budget.get("material_plan") or {}
    delivery = package.get("delivery") or {}
    currency = budget.get("currency") or "CNY"
    delivery_html = ('<h2>交付方式</h2><p><strong>'+esc(delivery.get('label') or '未选择')+'</strong></p>'
                     + '<p>下料：'+esc(delivery.get('cutting') or '未确定')
                     + ' · 装配：'+esc(delivery.get('assembly') or '未确定')
                     + ' · 材料：'+esc(delivery.get('material') or '未确定')+'</p>'
                     + ('<p>工具：'+esc('、'.join(delivery.get('tools') or []))+'</p>' if delivery.get('tools') else '')
                     + ('<p class="note">'+esc(delivery.get('note'))+'</p>' if delivery.get('note') else ''))
    def money(value):
        return "未填写" if value is None else f"{float(value):,.2f} {currency}"
    procurement = table(['零件', '材料', '毛坯尺寸 mm', '数量'], [[p['name'], p.get('material_name'), ' × '.join(f'{value:.3f}'.rstrip('0').rstrip('.') for value in p['stock_size_mm']), p['quantity']] for p in cuts])
    hardware_table = table(['五金', '规格', '数量'], [[h['name'],h['spec'],h['quantity']] for h in hardware])
    sheet_rows = []
    for line in plan.get('materials', []):
        stock = line.get('stock_dimensions_mm')
        sheets = line.get('sheet_count')
        sheet_rows.append([
            line.get('name'), ' × '.join(f'{float(v):.0f}' for v in stock) + ' mm' if stock else '未设置板幅',
            '—' if sheets is None else sheets, money(line.get('price_per_stock')),
            money(line.get('subtotal')),
            '—' if not line.get('utilization') else f"{line['utilization']*100:.1f}%",
        ])
    sheet_table = table(['材料', '板幅', '整板张数', '单价', '板材小计', '利用率'], sheet_rows)
    budget_table = table(['类别', '金额', '说明'], [
        ['板材', money(budget.get('material_subtotal')), '按整板排板估算'],
        ['五金', money(budget.get('hardware_subtotal')), '按示例单价' if budget.get('hardware_subtotal') is not None else '单价未设置'],
        ['加工', money(budget.get('processing_subtotal')), '开料/钻孔 + 装配'],
        ['表面', money(budget.get('finish_subtotal')), '打磨/涂装'],
        ['合计', money(budget.get('total')), '已填单价项合计'],
    ])
    budget_line_table = table(['类别', '项目', '数量', '单位', '单价', '金额'], [
        [line.get('category'), line.get('item'), line.get('quantity'), line.get('unit'),
         money(line.get('unit_price')), money(line.get('amount'))]
        for line in budget.get('lines', [])
    ])
    assembly = ''.join('<li><strong>'+esc(step.get('name') or step.get('joint_id'))+'</strong><p>'+esc(step.get('instruction'))+'</p></li>' for step in package.get('assembly_steps', []))
    drawing_pages = ''.join('<section class="drawing"><div class="sheet-label">'+esc(project['name'])+' · v'+str(project['revision'])+' · '+esc(d.get('id'))+'</div>'+d['svg']+'</section>' for d in package.get('drawings', []))
    overview = ''.join('<figure><img alt="'+label+'" src="data:image/png;base64,'+base64.b64encode(images[name]).decode('ascii')+'"><figcaption>'+label+' · v'+str(project['revision'])+'</figcaption></figure>' for name,label in [('assembled','整椅参考'),('exploded','板件装配关系')] if name in (images or {}))
    def schematic_svg():
        parts = project.get('parts') or []
        if not parts:
            return ''
        shapes = []
        for part in parts:
            size = part.get('size_mm') or [0, 0, 0]
            pos = part.get('position_mm') or [0, 0, 0]
            rx, ry, rz = [math.radians(float(value)) for value in (part.get('rotation_deg') or [0, 0, 0])]
            cx, cy, cz = math.cos(rx), math.cos(ry), math.cos(rz)
            sx, sy, sz = math.sin(rx), math.sin(ry), math.sin(rz)
            matrix = [[cy * cz, -cy * sz, sy], [cx * sz + sx * sy * cz, cx * cz - sx * sy * sz, -sx * cy], [sx * sz - cx * sy * cz, sx * cz + cx * sy * sz, cx * cy]]
            points = []
            for dx in (-size[0] / 2, size[0] / 2):
                for dy in (-size[1] / 2, size[1] / 2):
                    for dz in (-size[2] / 2, size[2] / 2):
                        local = (dx, dy, dz)
                        world = [pos[i] + sum(matrix[i][j] * local[j] for j in range(3)) for i in range(3)]
                        points.append(world)
            projected = [((point[0] - point[2]) * 0.866, (point[0] + point[2]) * 0.5 - point[1]) for point in points]
            xs = [point[0] for point in projected]; ys = [point[1] for point in projected]
            shapes.append((sum(point[0] + point[2] for point in points) / len(points), min(xs), max(xs), min(ys), max(ys)))
        if not shapes:
            return ''
        min_x = min(shape[1] for shape in shapes); max_x = max(shape[2] for shape in shapes)
        min_y = min(shape[3] for shape in shapes); max_y = max(shape[4] for shape in shapes)
        span_x = max(1, max_x - min_x); span_y = max(1, max_y - min_y)
        scale = min(92 / span_x, 108 / span_y)
        colors = ['#d8c9a8', '#cbb890', '#e2d6ba', '#bda77f', '#d2c29f', '#c7b28a']
        body = []
        for index, (depth, x0, x1, y0, y1) in enumerate(sorted(shapes, key=lambda item: -item[0])):
            x = 4 + (x0 - min_x) * scale
            y = 4 + (max_y - y1) * scale
            width = max(1, (x1 - x0) * scale); height = max(1, (y1 - y0) * scale)
            body.append('<rect x="' + f'{x:.2f}' + '" y="' + f'{y:.2f}' + '" width="' + f'{width:.2f}' + '" height="' + f'{height:.2f}' + '" fill="' + colors[index % len(colors)] + '" stroke="#8f7b57" stroke-width="0.6"/>')
        return '<svg viewBox="0 0 100 116" role="img" aria-label="整椅等轴示意"><rect x="0" y="0" width="100" height="116" fill="#f7f4ec"/>' + ''.join(body) + '</svg>'

    def layout_svg(line):
        stock = line.get('stock_dimensions_mm')
        if not stock:
            return ''
        length, width = float(stock[0]), float(stock[1])
        sheets = []
        for sheet in line.get('sheets', []):
            rects = []
            for shelf in sheet.get('shelves', []):
                for item in shelf.get('items', []):
                    rects.append('<rect x="' + f'{item["x"]:.1f}' + '" y="' + f'{item["y"]:.1f}' + '" width="' + f'{item["width"]:.1f}' + '" height="' + f'{item["height"]:.1f}' + '" fill="#d9c9a8" stroke="#9b8967" stroke-width="2"/>')
                    if item.get('width', 0) > length * 0.12:
                        rects.append('<text x="' + f'{item["x"] + 18:.1f}' + '" y="' + f'{item["y"] + 42:.1f}' + '" font-size="40" fill="#5f5849">' + esc(item.get('name', '')) + '</text>')
            sheets.append('<div class="layout-sheet"><svg viewBox="0 0 ' + f'{length:.0f} {width:.0f}' + '" aria-label="整板排板">' + ''.join(rects) + '</svg><small>第 ' + str(sheet.get('number', '?')) + ' 张 · ' + f'{length:.0f}' + '×' + f'{width:.0f}' + ' mm</small></div>')
        return ''.join(sheets)

    total = budget.get('total')
    parts_count = len(project.get('parts', []) or cuts)
    joints_count = len(project.get('joints', []))
    drawing_count = len(package.get('drawings', []))
    coverage = package.get('coverage', {}).get('not_checked', [])
    reference = bool(project.get('reconstruction'))
    budget_source = str(budget.get('source') or '')
    rate_note = '示例费率，不是加工店报价' if ('示例' in budget_source or not budget_source) else '费率来源：' + budget_source
    facts = ''.join('<div class="fact"><b>'+esc(value)+'</b><span>'+esc(label)+'</span></div>' for value, label in [
        (parts_count, '块板件'), (joints_count, '处连接'), (plan.get('sheet_total', '—'), '张整板'), (drawing_count, '张图纸')])
    index = ''.join('<li><span>'+esc(number)+'</span><b>'+esc(title)+'</b><small>'+esc(detail)+'</small></li>' for number, title, detail in [
        ('01', '采购与板料', '零件毛坯、五金、整板'),
        ('02', '预算', '材料、五金、加工、表面'),
        ('03', '交付与装配', '谁做什么、怎么装、图纸目录'),
        ('04', '加工图纸', str(drawing_count) + ' 张，逐件标注'),
    ])
    cover = (
        '<section class="cover">'
        '<div class="cover-top"><div><div class="eyebrow">JUNIOR · 椅子加工包</div>'
        '<h1>' + esc(project['name']) + '</h1>'
        '<p class="sub">v' + str(project['revision']) + ' · ' + str(parts_count) + ' 块板 · ' + str(joints_count) + ' 处连接</p></div>'
        '<div class="stamp">' + esc(delivery.get('label') or '交付方式未选') + '</div></div>'
        '<div class="cover-main"><div class="cover-visual">' + (layout_svg(plan['materials'][0]) if plan.get('materials') else '<div class="schematic-empty">还没有整板排板</div>') + '<small>整板排板 · 共 ' + str(plan.get('sheet_total', '—')) + ' 张 · 不是最优排版</small></div>'
        '<div class="cover-side"><div class="total"><span>预算合计</span><strong>' + money(total) + '</strong>'
        '<small>' + esc(rate_note) + '</small></div><div class="facts">' + facts + '</div></div></div>'
        '<div class="cover-grid"><section><div class="eyebrow">这一包里有什么</div><ol class="index">' + index + '</ol></section>'
        '<section><div class="eyebrow">钱花在哪</div>' + budget_table + '</section></div>'
        '<div class="cover-next"><div><span>下一步 1</span><b>核对价格</b><small>把示例费率换成本地加工店报价</small></div><div><span>下一步 2</span><b>买整板</b><small>按整板张数买，不按零件面积</small></div><div><span>下一步 3</span><b>下料打孔</b><small>把 PDF / SVG 和孔位表交给加工店</small></div><div><span>下一步 4</span><b>装配验收</b><small>按装配顺序，先试装再锁紧</small></div></div>'
        '<div class="notice"><b>先看边界</b><p>'
        + ('这是公开资料参考重建，不是原版实物测绘；' if reference else '')
        + '价格按示例费率，不是加工店报价；承载、连接强度、稳定性和加工公差未验证。'
        + ('未覆盖：' + esc('；'.join(coverage)) if coverage else '') + '</p></div>'
        '<div class="cover-foot">项目 ' + esc(project['id']) + ' · 版 v' + str(project['revision']) + ' · 所有资料来自同一版本</div>'
        '</section>'
    )
    visuals = ('<section class="page visuals-page"><div class="page-head"><span class="eyebrow">整体</span><h2>装配关系</h2></div>'
               '<div class="visuals">' + overview + '</div></section>') if overview else ''
    procurement_page = (
        '<section class="page"><div class="page-head"><span class="eyebrow">01 / 采购</span><h2>买什么，开几张板</h2></div>'
        '<h3>零件毛坯</h3>' + procurement + '<h3>五金</h3>' + hardware_table + '<h3>整板用料与预算</h3>' + sheet_table
        + '<p class="note">整板数量按矩形毛坯、3 mm 锯缝、10 mm 切边和货架式排板估算，不是最优排版；异形件按外接矩形，未计缺陷、纹理匹配、封边和损耗。单价为空时不编价格。</p></section>'
    )
    budget_page = (
        '<section class="page"><div class="page-head"><span class="eyebrow">02 / 预算</span><h2>钱花在哪</h2></div>'
        + budget_table + budget_line_table
        + '<div class="budget-read"><section><h3>怎么读这张预算</h3><ul><li>板材按整板张数计，不按零件面积切碎卖。</li><li>五金按数量乘单价，未填单价不会自动补价。</li><li>加工包含开料/钻孔和装配；表面是打磨/涂装。</li></ul></section><section><h3>报价前还要确认</h3><ul><li>' + esc(rate_note) + '。</li><li>木材缺陷、纹理匹配、封边和损耗未计。</li><li>承载、连接强度和稳定性未验证。</li></ul></section></div>'
        + '<p class="note">单价为空的项目不计金额，不编造价格。</p></section>'
    )
    drawing_index = ''.join('<li><span>'+str(i).zfill(2)+'</span><b>'+esc(d.get('title') or d.get('id'))+'</b><small>'+esc(d.get('id'))+'</small></li>' for i, d in enumerate(package.get('drawings', []), 1))
    cut_total = sum(len(line.get('sheets', [])) for line in plan.get('materials', []))
    cut_pages = []
    cut_number = 0
    for line in plan.get('materials', []):
        for sheet in line.get('sheets', []):
            cut_number += 1
            one = {**line, 'sheets': [sheet]}
            cut_pages.append(
                '<section class="cut-page"><div class="wide-head"><span class="eyebrow">下料 ' + str(cut_number).zfill(2) + ' / ' + str(cut_total).zfill(2) + '</span>'
                '<h2>' + esc(line.get('name')) + ' · 第 ' + str(sheet.get('number', '?')) + ' 张</h2>'
                '<small>' + ' × '.join(f'{float(v):.0f}' for v in (line.get('stock_dimensions_mm') or [])) + ' mm · 利用率 ' + (f"{line['utilization']*100:.1f}%" if line.get('utilization') is not None else '—') + '</small></div>'
                '<div class="cut-svg">' + layout_svg(one) + '</div></section>'
            )
    cut_pages = ''.join(cut_pages)
    handoff_page = (
        '<section class="page"><div class="page-head"><span class="eyebrow">03 / 交付与装配</span><h2>谁做什么，怎么装</h2></div>'
        '<div class="delivery-box"><strong>' + esc(delivery.get('label') or '交付方式未选') + '</strong>'
        '<p>下料：' + esc(delivery.get('cutting') or '未确定') + ' · 装配：' + esc(delivery.get('assembly') or '未确定')
        + ' · 材料：' + esc(delivery.get('material') or '未确定') + '</p>'
        + ('<p>工具：' + esc('、'.join(delivery.get('tools') or [])) + '</p>' if delivery.get('tools') else '')
        + ('<p class="note">' + esc(delivery.get('note')) + '</p>' if delivery.get('note') else '') + '</div>'
        + '<h3>装配顺序</h3><ol class="assembly-list">' + assembly + '</ol>'
        + '<h3>图纸目录</h3><ul class="drawing-index">' + drawing_index + '</ul></section>'
    )
    drawing_pages = ''.join(
        '<section class="drawing-page"><div class="drawing-head"><span class="eyebrow">图纸 ' + str(i).zfill(2) + ' / ' + str(drawing_count) + '</span>'
        '<h2>' + esc(d.get('title') or d.get('id')) + '</h2><small>' + esc(project['name']) + ' · v' + str(project['revision']) + ' · ' + esc(d.get('id')) + '</small></div>'
        '<div class="drawing-svg">' + d['svg'] + '</div></section>'
        for i, d in enumerate(package.get('drawings', []), 1)
    )
    return '''<!doctype html><html lang="zh"><meta charset="utf-8"><style>
@page { size:A4 portrait; margin:12mm; }
@page wide { size:A3 landscape; margin:8mm; }
* { box-sizing:border-box; } body { margin:0; color:#26332d; font:9.5pt/1.5 "Microsoft YaHei","Noto Sans CJK SC",sans-serif; }
h1 { font-size:24pt; line-height:1.12; letter-spacing:-.5pt; margin:2mm 0 2mm; } h2 { font-size:15pt; margin:0 0 2mm; } h3 { font-size:9pt; margin:5mm 0 1.5mm; color:#4f5b52; }
p,li { line-height:1.55; } table { width:100%; border-collapse:collapse; margin:0 0 3mm; table-layout:auto; }
th,td { padding:4px 6px; border:1px solid #ccd3cb; text-align:left; vertical-align:top; font-size:8.5pt; overflow-wrap:anywhere; } th { background:#eef1e9; } tr { break-inside:avoid; }
.eyebrow { font-size:7pt; letter-spacing:1.2pt; text-transform:uppercase; color:#7a8279; }
.cover { min-height:273mm; display:flex; flex-direction:column; page-break-after:always; }
.cover-top { display:flex; justify-content:space-between; gap:8mm; align-items:flex-start; }
.cover-top .sub { color:#657064; margin:1mm 0 0; }
.stamp { border:1px solid #b85e41; color:#b85e41; border-radius:3mm; padding:2mm 3mm; font-size:8pt; font-weight:600; max-width:50mm; text-align:right; }
.cover-main { display:grid; grid-template-columns:1.08fr .92fr; gap:6mm; margin:7mm 0 6mm; align-items:stretch; }
.cover-visual { background:#f7f4ec; border:1px solid #ded7c5; border-radius:3mm; padding:3mm; display:flex; flex-direction:column; }
.cover-visual .layout-sheet { border:0; padding:0; } .cover-visual .layout-sheet svg { width:100%; height:78mm; object-fit:contain; } .cover-visual .layout-sheet small { display:none; }
.cover-visual small { margin-top:auto; color:#7a8279; font-size:7pt; }
.schematic-empty { height:88mm; display:grid; place-items:center; color:#7a8279; font-size:8pt; }
.cover-side { display:flex; flex-direction:column; gap:4mm; }
.total { background:#f2eee3; border:1px solid #ded7c5; border-radius:3mm; padding:4mm 5mm; }
.total span { display:block; font-size:7.5pt; color:#657064; } .total strong { display:block; font-size:28pt; line-height:1.1; margin:2mm 0; color:#26332d; } .total small { font-size:7.5pt; color:#657064; }
.facts { display:grid; grid-template-columns:1fr 1fr; gap:3mm; }
.fact { background:#fbfaf5; border:1px solid #e5e1d7; border-radius:3mm; padding:3.5mm; }
.fact b { display:block; font-size:18pt; line-height:1.1; } .fact span { font-size:7.5pt; color:#657064; }
.cover-grid { display:grid; grid-template-columns:1.05fr .95fr; gap:7mm; align-items:start; }
ol.index { list-style:none; margin:2mm 0 0; padding:0; display:grid; gap:2.5mm; }
ol.index li { display:grid; grid-template-columns:7mm 1fr; grid-template-rows:auto auto; column-gap:2mm; border-bottom:1px solid #ece8dd; padding-bottom:2mm; }
ol.index li span { grid-row:1 / 3; color:#b85e41; font-size:9pt; } ol.index li b { font-size:9.5pt; } ol.index li small { color:#657064; font-size:7.5pt; }
.cover-next { display:grid; grid-template-columns:repeat(4,1fr); gap:3mm; margin-top:6mm; }
.cover-next div { border-top:2px solid #b85e41; padding-top:2mm; display:flex; flex-direction:column; gap:1mm; }
.cover-next span { font-size:7pt; color:#b85e41; } .cover-next b { font-size:9pt; } .cover-next small { font-size:7pt; color:#657064; line-height:1.4; }
.notice { margin-top:6mm; background:#f7f2e9; border-left:2mm solid #b85e41; padding:3mm 4mm; font-size:8pt; }
.notice p { margin:1mm 0 0; color:#586457; }
.cover-foot { margin-top:auto; padding-top:4mm; color:#7a8279; font-size:7pt; }
.page { break-before:page; }
.cut-page, .drawing-page { page: wide; break-before:page; width:404mm; height:281mm; display:flex; flex-direction:column; }
.wide-head { flex:0 0 auto; } .wide-head h2 { margin:1mm 0; } .wide-head small { color:#7a8279; font-size:8pt; }
.cut-svg { flex:1; min-height:0; display:flex; align-items:center; justify-content:center; }
.cut-svg .layout-sheet { border:0; padding:0; width:100%; height:100%; display:flex; align-items:center; justify-content:center; }
.cut-svg .layout-sheet svg { width:100%; height:100%; object-fit:contain; }
.cut-svg .layout-sheet small { display:none; }
.page-head { margin-bottom:5mm; }
.page-head h2 { margin-top:1mm; }
.layouts { display:grid; grid-template-columns:repeat(auto-fit,minmax(80mm,1fr)); gap:4mm; margin-bottom:2mm; } .layout-sheet { border:1px solid #e5e1d7; background:#fff; padding:2mm; } .layout-sheet svg { display:block; width:100%; height:58mm; object-fit:contain; } .layout-sheet small { display:block; color:#7a8279; font-size:7pt; margin-top:1mm; }
.budget-read { display:grid; grid-template-columns:1fr 1fr; gap:5mm; margin:3mm 0; border-top:1px solid #ece8dd; padding-top:3mm; } .budget-read ul { padding-left:4mm; margin:1mm 0; } .budget-read li { font-size:8pt; color:#586457; }
.visuals { display:grid; grid-template-columns:1fr 1fr; gap:4mm; } .visuals figure { margin:0; } .visuals img { width:100%; height:105mm; object-fit:contain; background:#f4f0e6; border:1px solid #e5e1d7; } figcaption { text-align:center; font-size:7.5pt; color:#657064; }
.delivery-box { background:#f7f5ee; border:1px solid #e5e1d7; border-radius:2mm; padding:3mm 4mm; margin-bottom:4mm; } .delivery-box strong { font-size:11pt; } .delivery-box p { margin:1mm 0; }
.assembly-list { padding-left:5mm; display:grid; gap:1.5mm; } .assembly-list li { padding-left:1mm; } .assembly-list strong { font-size:9pt; } .assembly-list p { margin:0.5mm 0 0; color:#4f5b52; }
.drawing-index { list-style:none; padding:0; margin:0; display:grid; grid-template-columns:1fr 1fr; gap:1.5mm 5mm; }
.drawing-index li { display:grid; grid-template-columns:7mm 1fr; column-gap:2mm; border-bottom:1px solid #ece8dd; padding:1.5mm 0; } .drawing-index li span { color:#b85e41; } .drawing-index li small { grid-column:2; color:#7a8279; font-size:7pt; }
.drawing-page { break-before:page; height:281mm; display:flex; flex-direction:column; }
.drawing-head { flex:0 0 auto; } .drawing-head small { color:#7a8279; font-size:7.5pt; }
.drawing-svg { flex:1; min-height:0; display:flex; align-items:center; justify-content:center; padding-top:3mm; }
.drawing-svg svg { width:100%; height:100%; object-fit:contain; }
.note { color:#657064; font-size:7.5pt; }
</style><body>''' + cover + visuals + procurement_page + budget_page + handoff_page + cut_pages + drawing_pages + '</body></html>'



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
        archive.writestr('purchase.csv', csv_bytes(['毛坯编号','材料','宽mm','厚mm','长mm','数量','说明'], [[c['part_id'],c.get('material_name'),*stock_dimensions(c),c['quantity'],'按零件毛坯；整板采购见 material-plan.csv'] for c in cuts]))
        plan = (package.get('budget') or {}).get('material_plan') or {}
        archive.writestr('material-plan.csv', csv_bytes(
            ['材料','板幅mm','整板张数','单价','板材小计','利用率','边角','状态'],
            [[line.get('name'),'×'.join(str(v) for v in (line.get('stock_dimensions_mm') or [])),
              line.get('sheet_count') if line.get('sheet_count') is not None else '',
              line.get('price_per_stock') if line.get('price_per_stock') is not None else '',
              line.get('subtotal') if line.get('subtotal') is not None else '',
              line.get('utilization') if line.get('utilization') is not None else '',
              line.get('offcut') if line.get('offcut') is not None else '',
              line.get('status')] for line in plan.get('materials', [])]))
        budget = package.get('budget') or {}
        budget_rows = [[line.get('category'), line.get('item'), line.get('quantity'), line.get('unit'),
                        line.get('unit_price'), line.get('amount'), '已计价' if line.get('priced') else '未计价']
                       for line in budget.get('lines', [])]
        budget_rows.append(['合计', '', '', '', '', budget.get('total'), '已填单价项合计'])
        archive.writestr('budget.csv', csv_bytes(
            ['类别','项目','数量','单位','单价','金额','说明'], budget_rows))
        archive.writestr('hardware.csv', csv_bytes(['名称','规格','数量'], [[h['name'],h['spec'],h['quantity']] for h in package.get('hardware', [])]))
        archive.writestr('assembly.txt', '\n\n'.join(f"{i}. {s.get('name') or s.get('joint_id')}\n{s.get('instruction', '')}" for i,s in enumerate(package.get('assembly_steps', []),1)))
        for name, image in (images or {}).items():
            archive.writestr('views/'+name+'.png', image)
        for index, drawing in enumerate(package.get('drawings', []), 1):
            archive.writestr(f"drawings/{index:03d}.svg", drawing['svg'])
        archive.writestr('README.txt', f"Junior 加工包 · v{project['revision']}\n模型、图纸与清单来自同一个版本。model/design.json 为可重新导入的模型数据。\n图纸以标注尺寸为准。material-plan.csv 为整板排板估算：矩形毛坯、3 mm 锯缝、10 mm 切边，不是最优排版；purchase.csv 为逐件毛坯。\n预算见 budget.csv：未填单价的项目不计金额，不编造价格。\n检查范围见 package.json 的 coverage；承载、稳定性及实际工艺需要实物核实。\n")
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
