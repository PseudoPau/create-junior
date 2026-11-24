"""Material planning is a purchase estimate, not a hidden nesting claim."""
import io
import zipfile
from copy import deepcopy

from app.workbench.costing import budget, plan_materials
from app.workbench.demo import cafe_candidate
from app.workbench.engine import build_package
from app.workbench.exports import archive_bytes, package_html
from app.workbench.models import Project


def sample():
    project = Project(references=[{'id': 'source', 'kind': 'note', 'name': 'Reference',
                                   'text': 'Explicit sample reference'}])
    return Project.model_validate({**project.model_dump(mode='json'), **cafe_candidate(project)['patch']})


def test_sample_six_board_chair_uses_one_birch_plywood_sheet():
    project = sample()
    plan = plan_materials(project.model_dump(mode='json'))
    assert plan['status'] == 'estimated'
    assert plan['sheet_total'] == 1
    assert plan['material_subtotal'] == 480
    assert plan['currency'] == 'CNY'
    line = plan['materials'][0]
    assert line['sheet_count'] == 1
    assert 0.13 < line['utilization'] < 0.15
    assert line['offcut'] > 0.85
    assert sorted(item['part_id'] for item in line['parts']) == sorted(part.id for part in project.parts)
    assert '示例单价' in line['price_note']


def test_missing_stock_does_not_invent_sheet_count():
    project = sample()
    data = project.model_dump(mode='json')
    for material in data['materials'].values():
        material.pop('stock_dimensions_mm', None)
    plan = plan_materials(data)
    assert plan['status'] == 'blocked'
    assert plan['sheet_total'] == 0
    assert plan['materials'][0]['status'] == 'missing_stock'
    assert plan['materials'][0]['sheet_count'] is None


def test_oversize_part_blocks_purchase_estimate():
    project = sample()
    data = project.model_dump(mode='json')
    for material in data['materials'].values():
        material['stock_dimensions_mm'] = [700, 300, 24]
    plan = plan_materials(data)
    assert plan['status'] == 'blocked'
    assert plan['materials'][0]['status'] == 'blocked'
    assert '放不进板幅' in plan['materials'][0]['reason']


def test_thickness_mismatch_blocks_estimate():
    project = sample()
    data = project.model_dump(mode='json')
    for material in data['materials'].values():
        material['stock_dimensions_mm'] = [2440, 1220, 18]
    plan = plan_materials(data)
    assert plan['status'] == 'blocked'
    assert plan['materials'][0]['status'] == 'thickness_mismatch'


def test_sample_budget_covers_material_hardware_processing_and_finish():
    project = sample()
    result = budget(project.model_dump(mode='json'))
    assert result['status'] == 'complete'
    assert result['material_subtotal'] == 480
    assert result['hardware_subtotal'] == 28.8
    assert result['processing_subtotal'] == 280
    assert result['finish_subtotal'] == 180
    assert result['total'] == 968.8
    assert result['missing_prices'] == []
    assert {line['category'] for line in result['lines']} == {'板材', '五金', '加工', '表面'}


def test_budget_without_rates_is_partial_and_does_not_invent_prices():
    project = sample()
    data = project.model_dump(mode='json')
    data.pop('costing', None)
    result = budget(data)
    assert result['status'] == 'partial'
    assert result['material_subtotal'] == 480
    assert result['hardware_subtotal'] is None
    assert result['processing_subtotal'] is None
    assert result['finish_subtotal'] is None
    assert result['total'] == 480
    assert '装配' in result['missing_prices']


def test_package_and_print_include_material_plan():
    project = sample()
    data = project.model_dump(mode='json')
    package = build_package(data)
    assert package['material_plan']['sheet_total'] == 1
    assert package['budget']['total'] == 968.8
    document = package_html(data, package)
    assert '整板用料与预算' in document
    assert '桦木海洋板' in document
    assert '480.00 CNY' in document
    assert '968.80 CNY' in document
    archive = zipfile.ZipFile(io.BytesIO(archive_bytes(data, package, b'pdf', document)))
    assert {'material-plan.csv', 'budget.csv', 'purchase.csv'} <= set(archive.namelist())
    plan_csv = archive.read('material-plan.csv').decode('utf-8-sig')
    budget_csv = archive.read('budget.csv').decode('utf-8-sig')
    assert '桦木海洋板' in plan_csv and ',1,' in plan_csv
    assert '板材,桦木海洋板' in budget_csv
    assert '五金,圆头内六角螺栓' in budget_csv
    assert '合计' in budget_csv
