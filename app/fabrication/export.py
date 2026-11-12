"""Portable export for the local fabrication package."""

from __future__ import annotations

import io
import json
import zipfile

from app.domain.models import DesignManifest
from app.fabrication.package import FabricationPackage, build_fabrication_package


def build_fabrication_archive(manifest: DesignManifest) -> tuple[FabricationPackage, bytes]:
    """Return the package and a self-contained zip for offline fabrication."""
    package = build_fabrication_package(manifest)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", manifest.model_dump_json(indent=2))
        archive.writestr("fabrication-package.json", package.model_dump_json(indent=2))
        archive.writestr(
            "README.txt",
            "Create Junior 加工包\n\n"
            "请先阅读 validation 和 joinery_notes；status 为 incomplete 时不要直接施工。\n",
        )
        for drawing in package.drawings:
            if drawing.svg:
                archive.writestr(f"drawings/{drawing.filename}", drawing.svg)
    return package, buffer.getvalue()
