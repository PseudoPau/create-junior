"""Build the two acceptance packages from repository data and print a report.

CAFE CHAIR is the explicit adaptation sample; its scale and joints are
confirmed here because acceptance is the user's decision, not the AI's.
PS 2026 is the public-reference reconstruction, not a measured master.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.workbench.demo import cafe_candidate
from app.workbench.engine import build_package
from app.workbench.exports import archive_bytes, package_html, render_pdf
from app.workbench.models import Project

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "design" / "acceptance"


def cafe_project() -> Project:
    base = Project(name="CAFE CHAIR · 改制样例", references=[
        {"id": "source", "kind": "note", "name": "仓库改制样例", "text": "示例数据，不是对当前参考的识别。"}
    ])
    data = {**base.model_dump(mode="json"), **cafe_candidate(base)["patch"]}
    data["scale"]["confirmed"] = True
    for joint in data["joints"]:
        joint["confirmed"] = True
    data["confirmed_revision"] = data["revision"]
    data["acknowledged_limits"] = True
    return Project.model_validate(data)


def ps_project() -> Project:
    return Project.model_validate(json.loads((ROOT / "examples/ps2026-reference-design.json").read_text(encoding="utf-8")))


def summary(label: str, project: Project) -> dict:
    data = project.model_dump(mode="json")
    package = build_package(data)
    assert package["status"] == "ready", (label, [c for c in package["checks"] if c["severity"] == "blocker"])
    budget = package["budget"]
    plan = package["material_plan"]
    assert budget["status"] == "complete"
    assert plan["status"] == "estimated"
    return {
        "label": label,
        "project": project.name,
        "revision": project.revision,
        "parts": len(project.parts),
        "joints": len(project.joints),
        "package_status": package["status"],
        "sheets": plan["sheet_total"],
        "material": budget["material_subtotal"],
        "hardware": budget["hardware_subtotal"],
        "processing": budget["processing_subtotal"],
        "finish": budget["finish_subtotal"],
        "total": budget["total"],
        "delivery": package["delivery"]["label"],
        "reference": project.reconstruction,
        "warnings": [c["code"] for c in package["checks"] if c["severity"] == "warning"],
    }


async def write_package(label: str, project: Project) -> None:
    data = project.model_dump(mode="json")
    package = build_package(data)
    html = package_html(data, package)
    pdf = await render_pdf(html)
    archive = archive_bytes(data, package, pdf, html)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{label}-v{project.revision}.pdf").write_bytes(pdf)
    (OUT / f"{label}-v{project.revision}.zip").write_bytes(archive)


async def main() -> None:
    cafe = cafe_project()
    ps = ps_project()
    rows = [summary("cafe-chair", cafe), summary("ps2026-reference", ps)]
    for row in rows:
        print(json.dumps(row, ensure_ascii=False))
        await write_package(row["label"], cafe if row["label"] == "cafe-chair" else ps)
    (OUT / "two-chairs-summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(row["total"] for row in rows)
    print(f"two-chair package total: {total:.2f} CNY")


if __name__ == "__main__":
    asyncio.run(main())
