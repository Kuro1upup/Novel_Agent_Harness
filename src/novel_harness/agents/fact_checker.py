"""Conservative fact-risk detection against traceable research notes."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from novel_harness.models.generation import FactRisk
from novel_harness.models.research import ResearchNote

from ._base import call_provider, format_prompt, load_prompt, make_model, unique_strings


class FactChecker:
    FACT_MARKERS = re.compile(
        r"\d|公元|朝代|法律|判刑|处方|剂量|症状|手术|警察|法院|银行|"
        r"经纪人|票房|收视率|公里|海拔|车程|航班|官职|礼制|货币|税"
    )

    def __init__(self, llm_provider: Any | None = None) -> None:
        self.llm_provider = llm_provider

    def check(
        self,
        draft: str,
        research_notes: Sequence[ResearchNote],
        *,
        project_id: str | None = None,
    ) -> list[FactRisk]:
        if not draft.strip():
            raise ValueError("draft is required")
        project_id = project_id or (research_notes[0].project_id if research_notes else "default")
        note_texts = {
            note.id: "\n".join(
                [
                    *note.extracted_facts,
                    *(evidence.text for evidence in note.evidence_snippets),
                ]
            )
            for note in research_notes
        }
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[。！？!?；;])", draft)
            if sentence.strip() and self.FACT_MARKERS.search(sentence)
        ]
        risks: list[FactRisk] = []
        for sentence in sentences:
            keywords = [
                token
                for token in re.findall(r"[\u4e00-\u9fff]{2,6}|\d+(?:\.\d+)?", sentence)
                if len(token) > 1
            ]
            supporting_notes = [
                note
                for note in research_notes
                if note.verification_status in {"fetched", "corroborated"}
                and any(token in note_texts[note.id] for token in keywords)
            ]
            if supporting_notes:
                level = "low"
                assessment = (
                    "确定"
                    if any(
                        note.verification_status == "corroborated" and note.credibility_score >= 0.7
                        for note in supporting_notes
                    )
                    else "可能有问题"
                )
                reason = "研究记录包含相关词条，但仍需核验原始来源与适用语境。"
                urls = unique_strings([str(note.source_url) for note in supporting_notes])
            else:
                level = "unknown"
                assessment = "不确定"
                reason = "现有研究记录不足以支持该可核查陈述。"
                urls = []
            risks.append(
                make_model(
                    FactRisk,
                    {
                        "project_id": project_id,
                        "claim": sentence[:300],
                        "assessment": assessment,
                        "risk_level": level,
                        "reason": reason,
                        "source_urls": urls,
                        "suggestion": (
                            "二次搜索该陈述涉及的时代、地域和具体制度，并优先使用官方、"
                            "学术或一手来源；核验前改写为人物主观判断。"
                        ),
                    },
                )
            )
        return risks

    async def acheck(self, *args: Any, **kwargs: Any) -> list[FactRisk]:
        baseline = self.check(*args, **kwargs)
        if self.llm_provider is None:
            return baseline
        prompt = format_prompt(
            load_prompt("fact_checker"),
            {
                "draft": args[0] if args else kwargs.get("draft"),
                "research_notes": args[1] if len(args) > 1 else kwargs.get("research_notes"),
                "rule_based_risks": baseline,
            },
        )
        try:
            result = await call_provider(self.llm_provider, prompt=prompt)
            rows = result.get("risks", []) if isinstance(result, dict) else []
            notes = args[1] if len(args) > 1 else kwargs.get("research_notes", [])
            project_id = kwargs.get("project_id") or (notes[0].project_id if notes else "default")
            additions = [FactRisk.model_validate({"project_id": project_id, **row}) for row in rows]
            return baseline + additions
        except Exception:
            return baseline

    async def run(self, *args: Any, **kwargs: Any) -> list[FactRisk]:
        return await self.acheck(*args, **kwargs)
