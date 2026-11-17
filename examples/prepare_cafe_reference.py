"""Import the three official CAFE CHAIR reference views."""
from pathlib import Path
from uuid import uuid4
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.workbench.models import Project, Reference, Evidence, Scale
from app.workbench.store import WorkbenchStore

root = Path(__file__).resolve().parents[1]
sources = root / ".data" / "cafe-chair-reference"
marker = sources / "project-id.txt"
store = WorkbenchStore(root / ".data" / "workbench")
if marker.exists():
    print(store.load(marker.read_text().strip()).id)
    raise SystemExit
project = Project(
    name="CAFE CHAIR · 参考资料",
    scope="supported",
    scope_reason="平直板材、直角切割、螺钉连接。",
    scale=Scale(kind="reference", confirmed=False, note="官方 W350 / D300（座深215）/ H780（座高450）mm。"),
    assumptions=[],
)
directory = store.directory(project.id) / "references"
directory.mkdir(parents=True, exist_ok=True)
for stem, label in (("front", "官方正面透视"), ("side", "官方侧面"), ("back", "官方背面")):
    source = sources / (stem + ".webp")
    ref_id = str(uuid4())
    (directory / ref_id).write_bytes(source.read_bytes())
    project.references.append(Reference(id=ref_id, name=label + ".webp",
        url=f"/api/workbench/projects/{project.id}/references/{ref_id}"))
project.evidence = [
    Evidence(statement="官方产品页给出整体宽350、深300、高780 mm；座深215、座高450 mm。",
             source_ids=[r.id for r in project.references], status="observed"),
    Evidence(statement="官方说明采用90度切割及螺钉连接；资料来源：https://ishinomaki-lab.org/en/products/cafe-chair-the-originals",
             status="observed"),
    Evidence(statement="原物料厚、孔位和内部连接：官方资料未提供。", status="unknown"),
]
store.save(project)
marker.write_text(project.id, encoding="utf-8")
print(project.id)
