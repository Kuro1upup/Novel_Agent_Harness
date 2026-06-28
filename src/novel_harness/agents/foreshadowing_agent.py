"""Foreshadowing planting and payoff proposals."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from novel_harness.models.story_bible import StoryBible

from ._base import call_provider, format_prompt, load_prompt


class ForeshadowingAction(BaseModel):
    action: Literal["plant", "reinforce", "payoff"]
    description: str
    subtle_expression: str
    target_payoff: str
    canon_risks: list[str] = Field(default_factory=list)


class ForeshadowingProposal(BaseModel):
    actions: list[ForeshadowingAction] = Field(default_factory=list)
    deferred_items: list[str] = Field(default_factory=list)


class ForeshadowingAgent:
    def __init__(self, llm_provider: Any | None = None) -> None:
        self.llm_provider = llm_provider

    def design(
        self,
        story_bible: StoryBible,
        scene_goal: str,
        *,
        max_actions: int = 3,
    ) -> ForeshadowingProposal:
        active = [
            item
            for item in story_bible.foreshadowing_items
            if getattr(item, "status", None) in {"planned", "planted"}
            or (isinstance(item, dict) and item.get("status") in {"planned", "planted"})
        ]
        actions: list[ForeshadowingAction] = []
        for item in active[:max_actions]:
            description = (
                item.get("description", "既有伏笔") if isinstance(item, dict) else item.description
            )
            status = item.get("status") if isinstance(item, dict) else item.status
            actions.append(
                ForeshadowingAction(
                    action="plant" if status == "planned" else "reinforce",
                    description=description,
                    subtle_expression=f"让与“{description}”相关的物件、反应或信息缺口自然影响行动",
                    target_payoff=(
                        item.get("expected_payoff") or "后续冲突"
                        if isinstance(item, dict)
                        else item.expected_payoff or "后续冲突"
                    ),
                    canon_risks=["不要让人物提前理解伏笔全貌"],
                )
            )
        if not actions:
            actions.append(
                ForeshadowingAction(
                    action="plant",
                    description=f"为场景目标“{scene_goal}”留下可验证的后果线索",
                    subtle_expression="通过动作结果或环境变化呈现，不使用旁白宣布这是伏笔",
                    target_payoff="后续两至五章的选择或冲突",
                    canon_risks=["接受草稿前应由作者确认是否写入 Story Bible"],
                )
            )
        return ForeshadowingProposal(actions=actions)

    async def adesign(self, *args: Any, **kwargs: Any) -> ForeshadowingProposal:
        baseline = self.design(*args, **kwargs)
        if self.llm_provider is None:
            return baseline
        prompt = format_prompt(
            load_prompt("foreshadowing_agent"),
            {"request": kwargs, "baseline": baseline},
        )
        return await call_provider(
            self.llm_provider,
            prompt=prompt,
            response_model=ForeshadowingProposal,
        )

    async def run(self, *args: Any, **kwargs: Any) -> ForeshadowingProposal:
        return await self.adesign(*args, **kwargs)
