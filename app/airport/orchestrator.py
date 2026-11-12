"""Airport integration orchestration for a confirmed design."""

from __future__ import annotations

from typing import Any

from app.airport.client import McpAirportClient
from app.airport.stool import build_box_plan
from app.domain.models import DesignManifest


async def commit_stool(client: McpAirportClient, manifest: DesignManifest) -> dict[str, Any]:
    project = await client.get_project()
    context_id = str(project["context_id"])
    meters_per_unit = float(project["meters_per_unit"])
    scene_units_per_mm = 0.001 / meters_per_unit
    plan = build_box_plan(manifest, scene_units_per_mm)
    committed = await client.import_topology_plan(plan, context_id)
    object_ids = [part["uuid"] for part in committed.get("parts", [])]
    return {
        "context_id": context_id,
        "meters_per_unit": meters_per_unit,
        "root_object_uuid": committed.get("object_uuid"),
        "part_object_uuids": object_ids,
        "plan": plan,
    }
