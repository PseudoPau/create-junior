"""Confirmation invalidation shared by preview and committed design updates."""
from app.workbench.models import Project


def invalidate_connections(previous: Project, data: dict) -> None:
    """Consent follows the selected construction method, never a geometry-valid flag.

    Resizing an adopted method does not change the user's decision. All current
    geometry is independently checked by the engine, including misaligned holes.
    Different hardware families, membership or connection types require adoption.
    """
    def method(joint):
        hardware = sorted((item.get('geometry') or {}).get('kind') or item.get('name', '')
                          for item in joint.get('hardware', []))
        return joint.get('kind'), sorted(joint.get('part_ids', [])), sorted(joint.get('feature_ids', [])), hardware

    previous_joints = {joint.id: joint.model_dump(mode='json') for joint in previous.joints}
    for joint in data.get('joints', []):
        prior = previous_joints.get(joint['id'])
        joint['confirmed'] = bool(prior and prior.get('confirmed') and method(prior) == method(joint))
    from app.workbench.review import invalidate_review
    invalidate_review(previous, data)
