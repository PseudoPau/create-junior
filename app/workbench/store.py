"""Atomic current document writes and immutable revisions; single-process local server."""
from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from uuid import UUID, uuid4
from app.workbench.models import Project, now
from app.workbench.revisions import invalidate_connections

class RevisionConflict(ValueError):
    pass

class WorkbenchStore:
    def __init__(self, root: Path | None = None):
        self.root = root or Path(os.getenv("CREATE_JUNIOR_DATA_DIR", ".data")) / "workbench"
        self.lock = RLock()

    def directory(self, project_id: str) -> Path:
        return self.root / str(UUID(str(project_id)))

    def atomic_json(self, path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
        fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                output.write(text)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def load(self, project_id: str) -> Project:
        # Immutable snapshot is the commit record; recover the current cache after interruption.
        with self.lock:
            directory = self.directory(project_id)
            path = directory / "project.json"
            snapshots = list((directory / "versions").glob("*.json"))
            latest = max(snapshots, key=lambda file: int(file.stem), default=None)
            current = Project.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None
            if latest is not None and (current is None or int(latest.stem) > current.revision):
                current = Project.model_validate_json(latest.read_text(encoding="utf-8"))
                self.atomic_json(path, current.model_dump(mode="json"))
            if current is None:
                raise FileNotFoundError(path)
            return current

    def save(self, project: Project) -> Project:
        directory = self.directory(project.id)
        snapshot = directory / "versions" / f"{project.revision}.json"
        if snapshot.exists():
            raise RevisionConflict("这个设计版本已存在")
        payload = project.model_dump(mode="json")
        self.atomic_json(snapshot, payload)
        self.atomic_json(directory / "project.json", payload)
        return project

    def change(self, project_id: str, expected: int, patch: dict, confirm=False,
               accepted_joint_ids: set[str] | None = None, restoring_snapshot: bool = False,
               review_actions: list[dict] | None = None, enable_review: bool = False) -> Project:
        with self.lock:
            previous = self.load(project_id)
            if previous.revision != expected:
                raise RevisionConflict("项目已被修改，请刷新后再提交")
            data = previous.model_dump(mode="json")
            if ('baseline_revision' in patch and previous.baseline_revision is not None
                    and patch['baseline_revision'] != previous.baseline_revision):
                raise ValueError("原版基线已经建立，不能被后续修改覆盖。")
            data.update(patch)
            if (review_actions or enable_review) and 'modules' not in patch:
                # A review click advances the revision but does not discard the
                # remaining suggestions from the same body/profile snapshot.
                from app.workbench.design_runs import DesignRuns
                advice = DesignRuns(self).current_advice(previous)
                if advice is not None:
                    data['modules'] = advice
            data = Project.model_validate(data).model_dump(mode="json")
            from app.workbench.preservation import preservation_conflict
            conflict = preservation_conflict(previous, data)
            if conflict and not restoring_snapshot:
                raise ValueError(conflict)
            if (not restoring_snapshot and data.get('preservation', {}).get('status') == 'verified'
                    and data['preservation'] != previous.preservation.model_dump(mode='json')):
                raise ValueError('保型规则需要独立校核，编辑操作不能自行标为已验证。')
            if not data["parts"] and (data.get("scale") or {}).get("confirmed"):
                raise ValueError("先形成模型，再核对并采用模型尺寸。")
            invalidate_connections(previous, data)
            # Only explicit server-side proposal/connection acceptance supplies these IDs.
            # This records design consent, not geometric validity or publication eligibility.
            if accepted_joint_ids:
                for joint in data["joints"]:
                    if joint["id"] in accepted_joint_ids:
                        joint["confirmed"] = True
            from app.workbench.review import apply_review_actions
            apply_review_actions(data, review_actions, enable_review)
            data["revision"] = previous.revision + 1
            data["updated_at"] = now()
            data["confirmed_revision"] = data["revision"] if confirm else None
            data["acknowledged_limits"] = bool(confirm)
            return self.save(Project.model_validate(data))

    def list_projects(self) -> list[dict]:
        result = []
        if not self.root.exists():
            return result
        for directory in self.root.iterdir():
            if not directory.is_dir():
                continue
            try:
                project = self.load(directory.name)
                result.append({"id": project.id, "name": project.name,
                               "revision": project.revision, "updated_at": project.updated_at})
            except (ValueError, OSError):
                continue
        return sorted(result, key=lambda item: item["updated_at"], reverse=True)

    def versions(self, project_id: str) -> list[dict]:
        self.load(project_id)
        result = []
        for path in (self.directory(project_id) / "versions").glob("*.json"):
            project = Project.model_validate_json(path.read_text(encoding="utf-8"))
            result.append({"revision": project.revision, "name": project.name,
                           "confirmed": project.confirmed_revision == project.revision})
        return sorted(result, key=lambda item: item["revision"], reverse=True)

    def restore(self, project_id: str, revision: int, expected: int) -> Project:
        if revision < 1:
            raise ValueError("无效版本")
        path = self.directory(project_id) / "versions" / f"{revision}.json"
        old = Project.model_validate_json(path.read_text(encoding="utf-8"))
        patch = old.model_dump(mode="json", exclude={"id", "revision", "updated_at",
                                                    "confirmed_revision", "acknowledged_limits", "baseline_revision"})
        return self.change(project_id, expected, patch,
                           accepted_joint_ids={joint.id for joint in old.joints if joint.confirmed},
                           restoring_snapshot=True)

    def save_proposal(self, project_id: str, proposal: dict):
        self.atomic_json(self.directory(project_id) / "proposals" / f"{UUID(proposal['id'])}.json", proposal)
        self.atomic_json(self.directory(project_id) / "proposal.json", proposal)

    def proposal(self, project_id: str, proposal_id: str | None = None) -> dict:
        directory = self.directory(project_id)
        path = directory / "proposals" / f"{UUID(proposal_id)}.json" if proposal_id else directory / "proposal.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def context(self) -> dict:
        path = self.root / "context.json"
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"preferences": {}, "inventory": []}
        data.setdefault("revision", 1)
        return data
