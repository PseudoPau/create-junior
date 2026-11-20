"""Explicit sample experience. Never interprets user references as this model."""
import json
from pathlib import Path
from app.workbench.proposals import build_proposal


def cafe_candidate(project):
    root = Path(__file__).resolve().parents[2] / "examples"
    base = json.loads((root / "cafe-chair-manufacturing-proposal.json").read_text(encoding="utf-8"))["patch"]
    base.update(json.loads((root / "cafe-chair-session-proposal.json").read_text(encoding="utf-8"))["patch"])
    base["name"] = "CAFE CHAIR · 改制样例"
    base["evidence"] = [{"statement": "本次加载仓库内改制样例，不是对当前参考的识别。官方原版宽350 mm、直角切割、黑色螺钉；本样例宽400 mm、24 mm板厚及斜切/螺栓连接属于演示方案。", "status": "adopted", "source_ids": []}]
    base["requirements"] = {"environment": "indoor", "notes": "改制样例仅用于编辑、联动和加工资料体验。"}
    base["fabrication_mode"] = "shop"
    base["modules"] = [{
        "id": "sitting-support",
        "kind": "support",
        "name": "坐姿支撑",
        "purpose": "支持成人坐姿使用，并保持座面与靠背的主要比例。",
        "occupant": "成人",
        "posture": "坐姿",
        "anthropometry": {"user_group": "adult"},
        "target": {"seat_width_mm": 400, "seat_depth_mm": 215, "seat_height_mm": 450, "back_angle_deg": 10},
        "constraints": [],
        "source_ids": [],
        "status": "target",
        "affected_part_ids": ["seat", "back", "side_left", "side_right", "foot_left", "foot_right"],
        "notes": "模块目标来自样例流程输入；人体工学范围需要按实际使用者和专业依据复核。"
    }]
    proposal = build_proposal(project, "加载现成 CAFE CHAIR 样例：6 个板件、400 mm 座宽、24 mm 白蜡木。用于体验编辑、连接检查和图纸；不代表 AI 已识别你的参考。", base, purpose="manufacturing")
    proposal["source"] = "demo"
    proposal["provider"] = "demo"
    return proposal
