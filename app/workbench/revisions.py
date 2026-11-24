"""Confirmation invalidation shared by preview and committed design updates."""
from app.workbench.models import Project


def _geometry(parts: dict, part_ids) -> tuple:
    """Every field that decides where material and holes actually sit."""
    signature = []
    for part_id in sorted(part_ids):
        part = parts.get(part_id)
        if part is None:
            signature.append((part_id, None))
            continue
        features = tuple(sorted(
            (feature.get('id'), feature.get('kind'), feature.get('face'),
             feature.get('u_mm'), feature.get('v_mm'), feature.get('depth_mm'),
             feature.get('diameter_mm'), feature.get('width_mm'), feature.get('length_mm'),
             tuple(feature.get('entry_mm') or ()), tuple(feature.get('direction_local') or ()))
            for feature in part.get('features', [])
        ))
        signature.append((
            part_id,
            tuple(part.get('size_mm') or ()),
            tuple(tuple(point) for point in part.get('outline_mm') or ()),
            tuple(tuple(cut.get('normal_local') or ()) + (cut.get('offset_mm'),)
                  for cut in part.get('plane_cuts') or ()),
            features,
        ))
    return tuple(signature)


def invalidate_connections(previous: Project, data: dict) -> None:
    """Confirmation binds to the material it was given for.

    Changing a connected part's stock size, outline, plane cut or hole/slot layout
    changes the actual construction, so the user must accept the connection again.
    Moving or rotating a part only changes where it sits: the method still stands and
    the geometry checks report separation and misalignment on their own.
    """
    def method(joint):
        hardware = sorted((item.get('geometry') or {}).get('kind') or item.get('name', '')
                          for item in joint.get('hardware', []))
        return joint.get('kind'), sorted(joint.get('part_ids', [])), sorted(joint.get('feature_ids', [])), hardware

    previous_joints = {joint.id: joint.model_dump(mode='json') for joint in previous.joints}
    previous_parts = {part.id: part.model_dump(mode='json') for part in previous.parts}
    current_parts = {part['id']: part for part in data.get('parts', [])}
    for joint in data.get('joints', []):
        prior = previous_joints.get(joint['id'])
        if not prior or not prior.get('confirmed') or method(prior) != method(joint):
            joint['confirmed'] = False
            continue
        part_ids = joint.get('part_ids', [])
        joint['confirmed'] = _geometry(previous_parts, part_ids) == _geometry(current_parts, part_ids)
    from app.workbench.review import invalidate_review
    invalidate_review(previous, data)
