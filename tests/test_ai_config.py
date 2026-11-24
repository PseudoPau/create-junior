"""AI credentials stay local, persist across restarts, and never return to the page."""
import json
import os

import pytest

from app.workbench import ai, api


def test_saved_ai_config_persists_without_exposing_key(tmp_path, monkeypatch):
    config = tmp_path / "ai-config.json"
    monkeypatch.setattr(ai, "CONFIG_PATH", config)
    for name in ("CREATE_JUNIOR_AI_PROVIDER", "CREATE_JUNIOR_AI_BASE_URL",
                 "CREATE_JUNIOR_AI_MODEL", "CREATE_JUNIOR_AI_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    ai.save_ai_config("openai_compatible", "https://example.test/v1", "vision-model", "sk-local-secret")
    assert oct(config.stat().st_mode & 0o777) == "0o600"
    data = json.loads(config.read_text())
    assert data["provider"] == "openai_compatible"
    assert data["api_key"] == "sk-local-secret"

    monkeypatch.setattr(api, "CONFIG_PATH", config)
    from fastapi.testclient import TestClient
    from app.main import app
    status = TestClient(app).get("/api/workbench/ai/status").json()
    assert status["provider"] == "openai_compatible"
    assert status["base_url"] == "https://example.test/v1"
    assert status["ready"] is True
    assert status["config_path"] == str(config)
    assert "sk-local-secret" not in json.dumps(status)


def test_ai_config_validation_rejects_bad_url_and_keeps_existing_key(tmp_path, monkeypatch):
    config = tmp_path / "ai-config.json"
    monkeypatch.setattr(ai, "CONFIG_PATH", config)
    monkeypatch.setenv("CREATE_JUNIOR_AI_API_KEY", "sk-existing")
    with pytest.raises(ValueError):
        ai.save_ai_config("openai", "not-a-url", "model", "")
    ai.save_ai_config("openai", "https://api.example.test/v1", "model", "")
    assert json.loads(config.read_text())["api_key"] == "sk-existing"
