"""Hardware access holes retain geometry checks without requiring a mating axis."""
from test_workbench_engine import example_project, blockers
from app.workbench.engine import build_checks, draw_part_svg
from app.workbench.models import Feature


def project_with_access_hole():
    project = example_project()
    project['parts'][1]['features'].append({
        'id': 'nut_access', 'kind': 'hole', 'role': 'hardware_access',
        'face': 'left', 'u_mm': 40, 'v_mm': 50,
        'diameter_mm': 10, 'depth_mm': 19,
    })
    project['joints'][0]['feature_ids'].append('nut_access')
    return project


def test_access_hole_does_not_need_another_parts_matching_axis():
    project = project_with_access_hole()
    assert not blockers(project)
    assert '五金安装孔' in draw_part_svg(project['parts'][1])


def test_access_hole_retains_bounds_and_joint_ownership_checks():
    project = project_with_access_hole()
    project['parts'][1]['features'][-1]['depth_mm'] = 21
    assert 'feature_invalid' in blockers(project)
    project = project_with_access_hole()
    project['joints'][0]['feature_ids'].remove('nut_access')
    assert 'features_unassigned' in {item['code'] for item in build_checks(project)}


def test_access_holes_cannot_replace_required_connection_features():
    project = example_project()
    for part in project['parts']:
        part['features'][0]['role'] = 'hardware_access'
    assert 'joint_feature_kind' in blockers(project)


def test_existing_features_default_to_connection_role():
    feature = example_project()['parts'][0]['features'][0]
    assert Feature.model_validate(feature).role == 'connection'
