"""The warehouse is user-managed local stock, not a project material plan."""
import json

import pytest

from app.workbench import warehouse


def test_warehouse_add_list_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(warehouse, "PATH", tmp_path / "warehouse.json")
    assert warehouse.list_items() == []
    item = warehouse.add_item({"name": "余料", "kind": "sheet", "dims": "300 × 400 mm", "quantity": 1})
    assert item["name"] == "余料"
    assert warehouse.list_items()[0]["id"] == item["id"]
    assert oct((tmp_path / "warehouse.json").stat().st_mode & 0o777) == "0o600"
    warehouse.delete_item(item["id"])
    assert warehouse.list_items() == []


def test_warehouse_rejects_bad_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(warehouse, "PATH", tmp_path / "warehouse.json")
    with pytest.raises(ValueError):
        warehouse.add_item({"name": "", "kind": "sheet"})
    with pytest.raises(ValueError):
        warehouse.add_item({"name": "x", "kind": "nope"})
    with pytest.raises(ValueError):
        warehouse.add_item({"name": "x", "quantity": 0})
