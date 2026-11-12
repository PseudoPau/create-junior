import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from app.analysis.models import ReferenceAnalysis
from app.analysis.provider import AIConfigurationError, OpenAICompatibleAnalyzer
from app.domain.models import DesignManifest, ReferenceSource


def test_openai_compatible_request_contains_evidence_guardrails():
    manifest = DesignManifest(
        name="AA Stool",
        reference_sources=[ReferenceSource(kind="url", uri="https://example.com/aa-stool")],
    )
    analyzer = OpenAICompatibleAnalyzer("https://api.example.test/v1", "secret", "vision-model")

    request = analyzer.build_request(manifest)

    assert request["model"] == "vision-model"
    assert request["response_format"] == {"type": "json_object"}
    assert "unknowns" in request["messages"][0]["content"]
    assert "aa-stool" in request["messages"][1]["content"][0]["text"]


def test_openai_compatible_response_becomes_reference_analysis():
    response_payload = {
        "choices": [{"message": {"content": json.dumps({
            "summary": "两个侧板和一个座面。",
            "style_notes": ["结构简洁"],
            "parts": [],
            "joinery": [],
            "unknowns": ["接合方式待确认"],
        }, ensure_ascii=False)}}]
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(200, json=response_payload)

    async def run() -> ReferenceAnalysis:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        analyzer = OpenAICompatibleAnalyzer("https://api.example.test/v1", "secret", "vision-model", client)
        manifest = DesignManifest(project_id=uuid4())
        result = await analyzer.analyze(manifest)
        await client.aclose()
        return result

    result = asyncio.run(run())

    assert result.status == "ready"
    assert result.provider == "vision-model"


def test_ai_configuration_requires_all_connection_values():
    with pytest.raises(AIConfigurationError):
        OpenAICompatibleAnalyzer("", "secret", "model")

