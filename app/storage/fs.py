"""Filesystem storage for local project manifests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID

from app.domain.models import DesignManifest


class ProjectStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(os.getenv("CREATE_JUNIOR_DATA_DIR", ".data"))
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, project_id: UUID) -> Path:
        return self.root / str(project_id) / "manifest.json"

    def save(self, manifest: DesignManifest) -> DesignManifest:
        path = self.path_for(manifest.project_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        return manifest

    def load(self, project_id: UUID) -> DesignManifest:
        path = self.path_for(project_id)
        return DesignManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
