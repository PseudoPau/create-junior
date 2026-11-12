"""Deterministic AA Stool geometry plan generation."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import DesignManifest


class DesignIncomplete(ValueError):
    pass


@dataclass(frozen=True)
class StoolDimensions:
    seat_height_mm: float
    seat_width_mm: float
    seat_depth_mm: float
    stock_thickness_mm: float


def dimensions_from_manifest(manifest: DesignManifest) -> StoolDimensions:
    profile = manifest.user_profile
    material = manifest.materials.get("main")
    missing: list[str] = []
    if profile.seat_height_mm is None:
        missing.append("seat_height_mm")
    if profile.seat_width_mm is None:
        missing.append("seat_width_mm")
    if profile.seat_depth_mm is None:
        missing.append("seat_depth_mm")
    if material is None or material.stock_thickness_mm is None:
        missing.append("materials.main.stock_thickness_mm")
    if missing:
        raise DesignIncomplete("Missing required stool dimensions: " + ", ".join(missing))
    return StoolDimensions(
        seat_height_mm=profile.seat_height_mm,
        seat_width_mm=profile.seat_width_mm,
        seat_depth_mm=profile.seat_depth_mm,
        stock_thickness_mm=material.stock_thickness_mm,
    )


def build_box_plan(manifest: DesignManifest, scene_units_per_mm: float) -> dict:
    dimensions = dimensions_from_manifest(manifest)
    h = dimensions.seat_height_mm * scene_units_per_mm
    w = dimensions.seat_width_mm * scene_units_per_mm
    d = dimensions.seat_depth_mm * scene_units_per_mm
    t = dimensions.stock_thickness_mm * scene_units_per_mm
    side_width = max(t * 2, 25 * scene_units_per_mm)

    return {
        "name": manifest.name,
        "parts": [
            {
                "kind": "box",
                "name": "Seat",
                "min": [-w / 2, -d / 2, h - t],
                "max": [w / 2, d / 2, h],
            },
            {
                "kind": "box",
                "name": "Side Left",
                "min": [-w / 2 - side_width, -d / 2, 0],
                "max": [-w / 2, d / 2, h - t],
            },
            {
                "kind": "box",
                "name": "Side Right",
                "min": [w / 2, -d / 2, 0],
                "max": [w / 2 + side_width, d / 2, h - t],
            },
        ],
    }
