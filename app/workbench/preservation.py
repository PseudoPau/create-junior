"""Shared geometric boundary for every edit channel, including generic PUT."""
from app.workbench.models import Project


def preservation_conflict(previous: Project, candidate: dict) -> str | None:
    if previous.baseline_revision is None or candidate.get('design_intent') == 'redesign':
        return None
    original = previous.model_dump(mode='json')
    def visible_shape(parts):
        return [{key: part.get(key) for key in ('id', 'kind', 'size_mm', 'position_mm',
                                                'rotation_deg', 'outline_mm', 'plane_cuts')}
                for part in parts]
    def connections(joints):
        return sorted(sorted(joint.get('part_ids', [])) for joint in joints)
    # Materials, drilling and hardware are making choices. They remain subject to
    # geometric checks but need no redesign when silhouette and structure stay.
    if (visible_shape(candidate.get('parts', [])) == visible_shape(original['parts'])
            and connections(candidate.get('joints', [])) == connections(original['joints'])):
        return None
    from app.workbench.module_fit import fit_preview, _layout
    try:
        for module in previous.modules:
            if module.kind != 'support':
                continue
            seat, back, _ = _layout(candidate, module.model_dump(mode='json'))
            values = {'seat_height_mm': seat['position_mm'][1] + seat['size_mm'][1] / 2,
                      'seat_width_mm': seat['size_mm'][0], 'seat_depth_mm': seat['size_mm'][2],
                      'back_angle_deg': -90 - back['rotation_deg'][0]}
            allowed = ['seat_height_mm']
            if previous.preservation.status == 'verified':
                allowed.extend(rule.key for rule in previous.preservation.limits
                               if rule.operator == 'range' and rule.key in values
                               and rule.min_mm <= values[rule.key] <= rule.max_mm)
            for key in allowed:
                expected = fit_preview(previous, module.id, key, values[key])['patch']
                if (visible_shape(candidate.get('parts', [])) == visible_shape(expected['parts'])
                        and connections(candidate.get('joints', [])) == connections(expected['joints'])):
                    return None
    except (ValueError, KeyError, TypeError, IndexError):
        pass
    return '这项改动超出原设计的已知保型规则。请保持原样，或明确作为改款预览；原版会保留。'
