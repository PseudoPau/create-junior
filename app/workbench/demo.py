"""Explicit sample experience. Never interprets user references as this model."""
import json
from pathlib import Path
from app.workbench.proposals import build_proposal


def cafe_candidate(project):
    root = Path(__file__).resolve().parents[2] / "examples"
    base = json.loads((root / "cafe-chair-manufacturing-proposal.json").read_text(encoding="utf-8"))["patch"]
    base.update(json.loads((root / "cafe-chair-session-proposal.json").read_text(encoding="utf-8"))["patch"])
    base["name"] = "CAFE CHAIR · 样例体验"
    base["evidence"] = [{"statement": "本次明确加载仓库内 CAFE CHAIR 样例，未识别或分析当前用户参考。", "status": "adopted", "source_ids": []}]
    base["requirements"] = {"environment": "indoor", "load_kg": 80, "notes": "流程演示使用条件；80 kg 是目标输入，不是承载能力结论。"}
    base["fabrication_mode"] = "shop"
    proposal = build_proposal(project, "加载现成 CAFE CHAIR 样例：6 个板件、400 mm 座宽、24 mm 白蜡木。用于体验编辑、连接检查和图纸；不代表 AI 已识别你的参考。", base, purpose="manufacturing")
    proposal["source"] = "demo"
    proposal["provider"] = "demo"
    return proposal
