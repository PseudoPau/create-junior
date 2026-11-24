"""A small local warehouse for leftovers the user chooses to keep.

It is deliberately separate from project geometry: project material plans are
estimates, not physical inventory. The user decides what to add.
"""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from app.workbench.models import now

PATH = Path(__file__).resolve().parents[2] / ".data" / "warehouse.json"


def _read() -> list[dict]:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def list_items() -> list[dict]:
    return _read()


def add_item(payload: dict) -> dict:
    name = str(payload.get("name") or "").strip()
    spec = str(payload.get("spec") or "").strip()
    dims = str(payload.get("dims") or "").strip()
    note = str(payload.get("note") or "").strip()[:500]
    kind = str(payload.get("kind") or "sheet").strip()
    if not name:
        raise ValueError("仓库条目需要名称。")
    if kind not in {"sheet", "profile", "hardware", "consumable"}:
        raise ValueError("仓库条目类型必须是 sheet、profile、hardware 或 consumable。")
    try:
        quantity = int(1 if payload.get("quantity") is None else payload.get("quantity"))
    except (TypeError, ValueError):
        raise ValueError("数量必须是整数。") from None
    if quantity < 1 or quantity > 10000:
        raise ValueError("数量必须在 1 到 10000 之间。")
    item = {"id": str(uuid4()), "name": name, "kind": kind, "spec": spec,
            "dims": dims, "quantity": quantity, "note": note, "created_at": now()}
    items = _read()
    items.append(item)
    PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(PATH)
    return item


def set_quantity(item_id: str, quantity: int) -> list[dict]:
    """Set an item quantity; zero removes it from the warehouse."""
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        raise ValueError("数量必须是整数。") from None
    if quantity < 0 or quantity > 10000:
        raise ValueError("数量必须在 0 到 10000 之间。")
    items = _read()
    item = next((entry for entry in items if entry.get("id") == item_id), None)
    if item is None:
        raise ValueError("仓库条目不存在。")
    if quantity == 0:
        items = [entry for entry in items if entry.get("id") != item_id]
    else:
        item["quantity"] = quantity
    PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(PATH)
    return items


def delete_item(item_id: str) -> list[dict]:
    items = [item for item in _read() if item.get("id") != item_id]
    PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(PATH)
    return items
