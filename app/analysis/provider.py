"""Provider-neutral reference analysis entry points."""

from __future__ import annotations

import json
import os
from typing import Any, Protocol

import httpx

from app.analysis.models import ReferenceAnalysis
from app.domain.models import DesignManifest


class ReferenceAnalyzer(Protocol):
    async def analyze(self, manifest: DesignManifest) -> ReferenceAnalysis: ...


class DraftReferenceAnalyzer:
    """A deterministic placeholder until an external vision provider is configured."""

    async def analyze(self, manifest: DesignManifest) -> ReferenceAnalysis:
        return ReferenceAnalysis(
            project_id=manifest.project_id,
            source_ids=[source.id for source in manifest.reference_sources],
            provider="draft",
            status="draft",
            summary="参考资料已保存，等待视觉模型分析。",
            unknowns=[
                "部件数量和真实尺寸尚未确认",
                "接合方式尚未确认",
                "材料属性尚未确认",
            ],
        )


class AIConfigurationError(RuntimeError):
    pass


class OpenAICompatibleAnalyzer:
    """Call a provider implementing the OpenAI chat-completions shape."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not base_url or not api_key or not model:
            raise AIConfigurationError("AI base URL, API key and model are required")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.client = client

    @classmethod
    def from_environment(cls) -> "OpenAICompatibleAnalyzer":
        return cls(
            base_url=os.getenv("CREATE_JUNIOR_AI_BASE_URL", ""),
            api_key=os.getenv("CREATE_JUNIOR_AI_API_KEY", ""),
            model=os.getenv("CREATE_JUNIOR_AI_MODEL", ""),
        )

    def build_request(self, manifest: DesignManifest) -> dict[str, Any]:
        sources = [
            {
                "id": source.id,
                "kind": source.kind,
                "uri": source.uri,
                "title": source.title,
                "description": source.description,
            }
            for source in manifest.reference_sources
        ]
        schema_hint = {
            "summary": "string",
            "style_notes": ["string"],
            "parts": [{"name": "string", "kind": "side_panel|seat_board|brace|unknown", "observations": ["string"], "dimensions": [{"name": "string", "value_mm": "number|null", "confidence": "confirmed|estimated|unknown"}]}],
            "joinery": [{"kind": "half_lap|dowel|screw|unknown", "part_names": ["string"], "rationale": "string", "confidence": "confirmed|estimated|unknown"}],
            "unknowns": ["string"],
        }
        return {
            "model": self.model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是木作家具结构分析助手。只分析参考资料，不把猜测当成事实。"
                        "输出 JSON，不输出 Markdown。所有无法从资料确认的内容放入 unknowns。"
                        f"JSON 结构提示：{json.dumps(schema_hint, ensure_ascii=False)}"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"project_name": manifest.name, "references": sources, "existing_evidence": [e.model_dump() for e in manifest.evidence]},
                        ensure_ascii=False,
                    ),
                },
            ],
        }

    async def analyze(self, manifest: DesignManifest) -> ReferenceAnalysis:
        client = self.client or httpx.AsyncClient(timeout=60)
        try:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=self.build_request(manifest),
            )
            response.raise_for_status()
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
            parsed = json.loads(content) if isinstance(content, str) else content
            return ReferenceAnalysis.model_validate({
                **parsed,
                "project_id": str(manifest.project_id),
                "source_ids": [source.id for source in manifest.reference_sources],
                "provider": self.model,
                "status": "ready",
            })
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return ReferenceAnalysis(
                project_id=manifest.project_id,
                source_ids=[source.id for source in manifest.reference_sources],
                provider=self.model,
                status="failed",
                summary="视觉分析失败，未写入结构候选。",
                unknowns=[str(exc)],
            )
        finally:
            if self.client is None:
                await client.aclose()


def configured_analyzer() -> ReferenceAnalyzer:
    names = ("CREATE_JUNIOR_AI_BASE_URL", "CREATE_JUNIOR_AI_API_KEY", "CREATE_JUNIOR_AI_MODEL")
    if all(os.getenv(name) for name in names):
        return OpenAICompatibleAnalyzer.from_environment()
    return DraftReferenceAnalyzer()
