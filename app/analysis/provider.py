"""Provider-neutral reference analysis entry points."""

from __future__ import annotations

from app.analysis.models import ReferenceAnalysis
from app.domain.models import DesignManifest


class DraftReferenceAnalyzer:
    """A deterministic placeholder until an external vision provider is selected."""

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
