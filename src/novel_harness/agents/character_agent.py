"""Character proposal agent."""

from __future__ import annotations

from typing import Any

from novel_harness.models.character import CharacterProfile
from novel_harness.models.story_bible import StoryBible

from ._base import call_provider, format_prompt, load_prompt, make_model


class CharacterAgent:
    def __init__(self, llm_provider: Any | None = None) -> None:
        self.llm_provider = llm_provider

    def create(
        self,
        *,
        name: str,
        role: str,
        story_bible: StoryBible | None = None,
        brief: str = "",
        project_id: str = "default",
    ) -> CharacterProfile:
        if not name.strip():
            raise ValueError("character name is required")
        canon = story_bible.world_summary if story_bible else ""
        data = {
            "project_id": project_id,
            "name": name.strip(),
            "role": role.strip(),
            "background": brief.strip() or f"{name}的背景尚待作者确认。",
            "motivation": f"完成其作为“{role or '剧情角色'}”的阶段目标",
            "desire": "推动当前目标达成",
            "fear": "失去重要关系或行动主动权",
            "secret": "未设定；不得擅自写入正文",
            "relationship_map": {},
            "speech_style": "措辞与身份、经历相符，避免全知式信息泄露",
            "arc_stage": "建立",
            "constraints": [
                "动机变化必须由可见事件触发",
                "不得掌握 Story Bible 未赋予的信息",
                *(["人物背景不得违反既有世界规则"] if canon else []),
            ],
        }
        return make_model(CharacterProfile, data)

    async def acreate(self, **kwargs: Any) -> CharacterProfile:
        baseline = self.create(**kwargs)
        if self.llm_provider is None:
            return baseline
        prompt = format_prompt(
            load_prompt("character_agent"),
            {
                "request": kwargs,
                "baseline": baseline,
                "story_bible": kwargs.get("story_bible"),
            },
        )
        return await call_provider(
            self.llm_provider,
            prompt=prompt,
            response_model=CharacterProfile,
        )

    async def run(self, **kwargs: Any) -> CharacterProfile:
        return await self.acreate(**kwargs)
