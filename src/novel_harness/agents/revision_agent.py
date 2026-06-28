"""Single-pass revision agent."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from novel_harness.models.generation import ContinuityIssue, FactRisk, GenerationResult

from ._base import call_provider_overlay, format_prompt, load_prompt, make_model


class RevisionAgent:
    def __init__(self, llm_provider: Any | None = None) -> None:
        self.llm_provider = llm_provider

    def revise(
        self,
        draft: GenerationResult | str,
        continuity_issues: Sequence[ContinuityIssue],
        fact_risks: Sequence[FactRisk],
        *,
        project_id: str | None = None,
    ) -> GenerationResult:
        if isinstance(draft, GenerationResult):
            project_id = project_id or draft.project_id
            body = draft.body
            source_urls = [str(url) for url in draft.source_urls]
            gaps = list(draft.research_gaps)
            bible_version = draft.bible_version
            prior_notes = draft.creative_notes
            factual_basis = draft.factual_basis_summary
        else:
            project_id = project_id or "default"
            body = draft
            source_urls = []
            gaps = []
            bible_version = 1
            prior_notes = ""
            factual_basis = ""
        if not body.strip():
            raise ValueError("draft is required")

        applied: list[str] = []
        for issue in continuity_issues:
            match = re.search(r"草稿写为\s*(\d+)\s*岁", issue.evidence)
            expected = re.search(r"设定为\s*(\d+)\s*岁", issue.evidence)
            if match and expected:
                body = re.sub(
                    rf"{match.group(1)}\s*岁",
                    f"{expected.group(1)}岁",
                    body,
                    count=1,
                )
                applied.append(issue.description)
        for risk in fact_risks:
            if risk.risk_level in {"high", "unknown"}:
                gaps.append(risk.claim[:120])
        note = (
            f"规则修订已应用 {len(applied)} 项；"
            f"另有 {len(continuity_issues) - len(applied)} 项连续性建议需作者判断，"
            f"{sum(r.risk_level in {'high', 'unknown'} for r in fact_risks)} 项事实需核验。"
        )
        return make_model(
            GenerationResult,
            {
                "project_id": project_id,
                "body": body,
                "creative_notes": "\n".join(part for part in (prior_notes, note) if part),
                "factual_basis_summary": factual_basis,
                "source_urls": source_urls,
                "research_gaps": list(dict.fromkeys(gaps)),
                "bible_version": bible_version,
            },
        )

    async def arevise(self, *args: Any, **kwargs: Any) -> GenerationResult:
        baseline = self.revise(*args, **kwargs)
        if self.llm_provider is None:
            return baseline
        prompt = format_prompt(
            load_prompt("revision_agent"),
            {
                "draft": args[0] if args else kwargs.get("draft"),
                "continuity_issues": (
                    args[1] if len(args) > 1 else kwargs.get("continuity_issues")
                ),
                "fact_risks": args[2] if len(args) > 2 else kwargs.get("fact_risks"),
                "rule_based_revision": baseline,
            },
        )
        return await call_provider_overlay(
            self.llm_provider,
            prompt=prompt,
            baseline=baseline,
            preserve=(
                "id",
                "project_id",
                "created_at",
                "updated_at",
                "bible_version",
                "source_urls",
                "object_key",
                "status",
                "retrieval_query",
                "context_sources",
            ),
        )

    async def run(self, *args: Any, **kwargs: Any) -> GenerationResult:
        return await self.arevise(*args, **kwargs)
