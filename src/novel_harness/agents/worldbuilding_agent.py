"""Worldbuilding proposal generation without mutating canon."""

from __future__ import annotations

from typing import Any

from novel_harness.models.creative import WorldbuildingProposal
from novel_harness.models.story_bible import StoryBible

from ._base import call_provider, format_prompt, load_prompt


class WorldbuildingAgent:
    def __init__(self, llm_provider: Any | None = None) -> None:
        self.llm_provider = llm_provider

    def propose(
        self,
        *,
        genre: str,
        premise: str,
        goal: str,
        story_bible: StoryBible | None = None,
    ) -> WorldbuildingProposal:
        existing = story_bible.world_summary if story_bible else ""
        return WorldbuildingProposal(
            world_summary=existing or f"{genre}故事世界：{premise}".strip("："),
            rules=[
                {
                    "name": "能力与代价对等",
                    "description": "任何显著能力必须有明确边界、代价与可观察后果。",
                    "status": "proposal",
                },
                {
                    "name": "信息获取有来源",
                    "description": "人物只能依据经历、调查或可信转述获得信息。",
                    "status": "proposal",
                },
            ],
            factions=[
                {
                    "name": "待命名对立势力",
                    "goal": f"阻碍或争夺：{goal}",
                    "resources": [],
                    "status": "proposal",
                }
            ],
            locations=[
                {
                    "name": "核心冲突地点",
                    "function": goal,
                    "constraints": [],
                    "status": "proposal",
                }
            ],
            research_gaps=([f"核验 {genre} 相关真实制度、地理与职业细节"] if genre else []),
        )

    async def apropose(self, **kwargs: Any) -> WorldbuildingProposal:
        baseline = self.propose(**kwargs)
        if self.llm_provider is None:
            return baseline
        prompt = format_prompt(
            load_prompt("worldbuilding_agent"),
            {"request": kwargs, "baseline": baseline},
        )
        return await call_provider(
            self.llm_provider,
            prompt=prompt,
            response_model=WorldbuildingProposal,
        )

    async def run(self, **kwargs: Any) -> WorldbuildingProposal:
        return await self.apropose(**kwargs)
