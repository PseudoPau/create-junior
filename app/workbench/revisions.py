"""Confirmation invalidation shared by preview and committed design updates."""
from app.workbench.models import Project


def invalidate_connections(previous: Project, data: dict) -> None:
    """Clear connection confirmations when their parts or materials changed in validated data."""
    old_parts = {p.id: p.model_dump(mode="json") for p in previous.parts}
    new_parts = {p["id"]: p for p in data.get("parts", [])}
    changed_parts = {pid for pid in set(old_parts) | set(new_parts)
                     if old_parts.get(pid) != new_parts.get(pid)}
    old_materials = previous.model_dump(mode="json")["materials"]
    changed_materials = {mid for mid in set(old_materials) | set(data.get("materials", {}))
                         if old_materials.get(mid) != data.get("materials", {}).get(mid)}
    changed_parts.update(p["id"] for p in data.get("parts", [])
                         if p.get("material_id") in changed_materials)
    if changed_parts:
        data["joints"] = [
            {**joint, "confirmed": False}
            if changed_parts.intersection(joint.get("part_ids", [])) else joint
            for joint in data.get("joints", [])
        ]
