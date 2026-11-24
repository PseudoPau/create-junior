"""Deterministic material planning and first-pass budget.

The planner uses rectangular part envelopes and a shelf packer. It is a
purchasing estimate, not a nesting optimiser: it never hides offcuts, defects,
grain matching or saw kerf behind a fake precision.
"""
from __future__ import annotations

from collections import defaultdict

from app.workbench.review_groups import board_dimensions

DEFAULT_KERF_MM = 3.0
DEFAULT_TRIM_MM = 10.0


def _rect(part: dict) -> dict:
    dimensions = board_dimensions(part)
    return {
        'part_id': part.get('id'),
        'name': part.get('name') or part.get('id'),
        'length_mm': float(dimensions['length_mm']),
        'width_mm': float(dimensions['width_mm']),
        'thickness_mm': float(dimensions['thickness_mm']),
    }


def _orientations(item: dict, allow_rotation: bool):
    first = (item['length_mm'], item['width_mm'], False)
    if not allow_rotation or abs(item['length_mm'] - item['width_mm']) < 0.001:
        return [first]
    return [first, (item['width_mm'], item['length_mm'], True)]


def _pack(items: list[dict], stock_length: float, stock_width: float,
          kerf: float, trim: float, allow_rotation: bool) -> dict:
    usable_length = stock_length - 2 * trim
    usable_width = stock_width - 2 * trim
    if usable_length <= 0 or usable_width <= 0:
        return {'status': 'blocked', 'reason': '板幅在切边后没有可用面积', 'sheets': []}
    ordered = sorted(items, key=lambda item: (max(item['length_mm'], item['width_mm']),
                                              item['length_mm'] * item['width_mm']),
                     reverse=True)
    sheets: list[dict] = []
    for item in ordered:
        placed = False
        for sheet in sheets:
            for shelf in sheet['shelves']:
                for width, height, rotated in _orientations(item, allow_rotation):
                    if height > shelf['height'] + 0.001:
                        continue
                    if shelf['x'] + (kerf if shelf['items'] else 0) + width > usable_length + 0.001:
                        continue
                    x = shelf['x'] + (kerf if shelf['items'] else 0)
                    shelf['items'].append({**item, 'x': x, 'y': shelf['y'],
                                           'width': width, 'height': height,
                                           'rotated': rotated})
                    shelf['x'] = x + width
                    placed = True
                    break
                if placed:
                    break
            if placed:
                break
            for width, height, rotated in _orientations(item, allow_rotation):
                if width > usable_length + 0.001:
                    continue
                y = sheet['y'] + (kerf if sheet['shelves'] else 0)
                if y + height > usable_width + 0.001:
                    continue
                sheet['shelves'].append({
                    'y': y, 'height': height, 'x': width,
                    'items': [{**item, 'x': 0, 'y': y, 'width': width,
                               'height': height, 'rotated': rotated}],
                })
                sheet['y'] = y + height
                placed = True
                break
            if placed:
                break
        if placed:
            continue
        for width, height, rotated in _orientations(item, allow_rotation):
            if width <= usable_length + 0.001 and height <= usable_width + 0.001:
                sheets.append({
                    'number': len(sheets) + 1, 'y': height,
                    'shelves': [{'y': 0, 'height': height, 'x': width,
                                 'items': [{**item, 'x': 0, 'y': 0, 'width': width,
                                            'height': height, 'rotated': rotated}]}],
                })
                placed = True
                break
        if not placed:
            return {'status': 'blocked',
                    'reason': f"{item['name']} 的毛坯 {item['length_mm']:.0f}×{item['width_mm']:.0f} mm 放不进板幅",
                    'sheets': sheets}
    used = sum(item['length_mm'] * item['width_mm'] for item in items)
    stock_area = len(sheets) * stock_length * stock_width
    return {
        'status': 'estimated',
        'sheets': sheets,
        'sheet_count': len(sheets),
        'used_area_mm2': round(used, 3),
        'stock_area_mm2': round(stock_area, 3),
        'utilization': round(used / stock_area, 4) if stock_area else 0,
        'offcut': round(1 - used / stock_area, 4) if stock_area else 0,
        'kerf_mm': kerf,
        'trim_mm': trim,
        'allow_rotation': allow_rotation,
    }


def plan_materials(project: dict) -> dict:
    materials = project.get('materials') or {}
    parts = project.get('parts') or []
    # One purchase sheet can supply several part materials when the physical
    # stock is identical. Grain is a per-part placement rule, not a separate
    # purchase unit; only solid wood with different grain directions stays split.
    groups: dict[tuple, dict] = {}
    for part in parts:
        material_id = part.get('material_id')
        material = materials.get(material_id) or {}
        signature = (
            material.get('name') or material_id,
            tuple(material.get('stock_dimensions_mm') or ()),
            material.get('price_per_stock'),
            material.get('currency') or 'CNY',
            material.get('kind'),
            material.get('grain_axis') if material.get('kind') != 'panel' else None,
        )
        groups.setdefault(signature, {'material': material, 'material_ids': [], 'parts': []})
        groups[signature]['material_ids'].append(material_id)
        groups[signature]['parts'].append(part)
    lines = []
    for signature, group in groups.items():
        material = group['material']
        material_parts = group['parts']
        material_ids = group['material_ids']
        name = material.get('name') or material_ids[0]
        stock = material.get('stock_dimensions_mm')
        price = material.get('price_per_stock')
        line = {
            'material_id': material_ids[0],
            'material_ids': material_ids,
            'name': name,
            'kind': material.get('kind'),
            'grain_axis': material.get('grain_axis'),
            'stock_dimensions_mm': stock,
            'price_per_stock': price,
            'currency': material.get('currency') or 'CNY',
            'price_note': material.get('price_note') or '',
            'part_count': len(material_parts),
            'parts': [_rect(part) for part in material_parts],
        }
        if not stock:
            line.update({'status': 'missing_stock', 'sheet_count': None,
                         'subtotal': None, 'sheets': []})
            lines.append(line)
            continue
        stock_length, stock_width, stock_thickness = (float(v) for v in stock)
        mismatched = [part['name'] for part in line['parts']
                      if abs(part['thickness_mm'] - stock_thickness) > 0.5]
        if mismatched:
            line.update({'status': 'thickness_mismatch', 'sheet_count': None,
                         'subtotal': None, 'sheets': [],
                         'detail': '零件厚度与板材厚度不一致：' + '、'.join(mismatched)})
            lines.append(line)
            continue
        allow_rotation = material.get('kind') == 'panel' or material.get('grain_axis') == 'unknown'
        packed = _pack(line['parts'], stock_length, stock_width,
                       DEFAULT_KERF_MM, DEFAULT_TRIM_MM, allow_rotation)
        line.update(packed)
        if packed['status'] == 'estimated':
            subtotal = None if price is None else round(packed['sheet_count'] * float(price), 2)
            line.update({'subtotal': subtotal,
                         'price_status': 'priced' if price is not None else 'unpriced'})
        lines.append(line)
    priced = [line for line in lines if line.get('subtotal') is not None]
    blocked = [line for line in lines if line.get('status') not in ('estimated',)]
    subtotal = round(sum(line['subtotal'] for line in priced), 2) if priced else None
    currencies = {line['currency'] for line in lines if line.get('subtotal') is not None}
    currency = currencies.pop() if len(currencies) == 1 else (next(iter(currencies), 'CNY') if currencies else 'CNY')
    return {
        'materials': lines,
        'sheet_total': sum(line.get('sheet_count') or 0 for line in lines),
        'material_subtotal': subtotal,
        'currency': currency,
        'status': 'blocked' if blocked else ('estimated' if len(priced) == len(lines) else 'partial'),
        'notes': [
            '按矩形毛坯外接尺寸和货架式排板估算，不是最优排版；异形件按外接矩形。',
            '已计 3 mm 锯缝与 10 mm 切边；未计木材缺陷、纹理匹配、封边和损耗。',
            '采购按整张板计；边角料保留在排板图中。',
        ],
    }


def budget(project: dict, hardware: list[dict] | None = None) -> dict:
    plan = plan_materials(project)
    if hardware is None:
        totals = defaultdict(int)
        for joint in project.get('joints') or []:
            for item in joint.get('hardware') or []:
                quantity = item.get('quantity')
                if isinstance(quantity, int) and not isinstance(quantity, bool) and quantity > 0:
                    totals[(str(item.get('name', '')), str(item.get('spec', '')))] += quantity
        hardware = [{'name': name, 'spec': spec, 'quantity': quantity}
                    for (name, spec), quantity in sorted(totals.items())]
    costing = project.get('costing') or {}
    currency = costing.get('currency') or plan['currency'] or 'CNY'
    lines: list[dict] = []
    missing: list[str] = []

    def add_line(category: str, item: str, quantity: float | None, unit: str,
                 unit_price: float | None, amount: float | None, note: str = '') -> None:
        lines.append({'category': category, 'item': item, 'quantity': quantity,
                      'unit': unit, 'unit_price': unit_price,
                      'amount': None if amount is None else round(amount, 2),
                      'priced': amount is not None, 'note': note})

    for material in plan['materials']:
        if material.get('sheet_count') is None:
            add_line('板材', material.get('name') or material.get('material_id'),
                     None, '张', material.get('price_per_stock'), None,
                     material.get('reason') or material.get('detail') or material.get('status'))
            missing.append(material.get('name') or material.get('material_id'))
            continue
        add_line('板材', material.get('name') or material.get('material_id'),
                 material.get('sheet_count'), '张', material.get('price_per_stock'),
                 material.get('subtotal'), '按整板排板估算')

    hardware_prices = costing.get('hardware_prices') or {}
    for item in hardware or []:
        name, spec, quantity = item.get('name'), item.get('spec'), item.get('quantity')
        key = f'{name}|{spec}'
        price = hardware_prices.get(key)
        if price is None:
            price = hardware_prices.get(name)
        amount = None if price is None else float(quantity) * float(price)
        add_line('五金', f'{name} · {spec}', quantity, '件', price, amount)
        if amount is None:
            missing.append(f'{name} · {spec}')

    sheet_total = plan.get('sheet_total') or 0
    cutting = costing.get('cutting_per_sheet')
    finish = costing.get('finish_per_sheet')
    hours = costing.get('assembly_hours')
    labor = costing.get('labor_per_hour')
    add_line('加工', '开料 / 钻孔', sheet_total, '张', cutting,
             None if cutting is None else sheet_total * float(cutting))
    add_line('加工', '装配', hours, '小时', labor,
             None if hours is None or labor is None else float(hours) * float(labor))
    add_line('表面', '打磨 / 涂装', sheet_total, '张', finish,
             None if finish is None else sheet_total * float(finish))
    if cutting is None:
        missing.append('开料 / 钻孔')
    if hours is None or labor is None:
        missing.append('装配')
    if finish is None:
        missing.append('打磨 / 涂装')

    def subtotal(category: str) -> float | None:
        items = [line for line in lines if line['category'] == category]
        if not items or any(line['amount'] is None for line in items):
            return None
        return round(sum(line['amount'] for line in items), 2)

    material_subtotal = subtotal('板材')
    hardware_subtotal = subtotal('五金')
    processing_subtotal = subtotal('加工')
    finish_subtotal = subtotal('表面')
    priced_total = round(sum(line['amount'] for line in lines if line['amount'] is not None), 2)
    complete = not missing and plan['status'] == 'estimated'
    status = 'blocked' if plan['status'] == 'blocked' else ('complete' if complete else 'partial')
    notes = list(plan['notes'])
    if missing:
        notes.append('未计价：' + '、'.join(dict.fromkeys(missing)))
    if costing.get('notes'):
        notes.append(costing['notes'])
    if costing.get('source'):
        notes.append('费率来源：' + costing['source'])
    return {
        'currency': currency,
        'material_subtotal': material_subtotal,
        'hardware_subtotal': hardware_subtotal,
        'processing_subtotal': processing_subtotal,
        'finish_subtotal': finish_subtotal,
        'total': priced_total,
        'status': status,
        'complete': complete,
        'lines': lines,
        'missing_prices': list(dict.fromkeys(missing)),
        'material_plan': plan,
        'notes': notes,
    }
