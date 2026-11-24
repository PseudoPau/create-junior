"""PS 2026 is a public-reference reconstruction, not a measured master."""
import json
from pathlib import Path

from app.workbench.engine import build_package
from app.workbench.models import Project

ROOT = Path(__file__).resolve().parents[1]


def project():
    return Project.model_validate(json.loads((ROOT / 'examples/ps2026-reference-design.json').read_text(encoding='utf-8')))


def test_reference_model_is_labelled_and_has_six_parts():
    model = project()
    assert model.reconstruction is True
    assert len(model.parts) == 6
    assert len(model.joints) == 6
    assert all(joint.kind == 'cam_lock' for joint in model.joints)


def test_reference_package_is_ready_with_a_reference_budget():
    data = project().model_dump(mode='json')
    package = build_package(data)
    assert package['status'] == 'ready'
    assert package['material_plan']['sheet_total'] == 1
    assert package['material_plan']['material_subtotal'] == 420
    assert package['budget']['status'] == 'complete'
    assert package['budget']['total'] == 984
    assert package['budget']['hardware_subtotal'] == 54
    assert package['budget']['processing_subtotal'] == 310
    assert package['budget']['finish_subtotal'] == 200
    codes = {check['code'] for check in package['checks']}
    assert 'cam_lock_geometry_approximate' in codes
    assert 'cam_lock_geometry_missing' not in codes
    assert not any(check['severity'] == 'blocker' for check in package['checks'])


def test_reference_package_declares_what_is_not_measured():
    data = project().model_dump(mode='json')
    package = build_package(data)
    text = ' '.join(data['assumptions'])
    assert '参考重建' in text
    assert '非实物测绘' in text
    assert '整椅承载与连接强度' in package['coverage']['not_checked']
