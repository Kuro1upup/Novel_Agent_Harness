"""Canon-aware deterministic plot planning."""

from __future__ import annotations

from typing import Any

from novel_harness.models.plot import PlotOption, PlotPlan
from novel_harness.models.story_bible import StoryBible

from ._base import call_provider_overlay, format_prompt, load_prompt, make_model


class PlotPlanner:
    def __init__(self, llm_provider: Any | None = None) -> None:
        self.llm_provider = llm_provider

    def plan(
        self,
        story_bible: StoryBible,
        current_summary: str,
        author_goal: str,
        *,
        project_id: str | None = None,
        retrieved_context: str = "",
    ) -> PlotPlan:
        project_id = project_id or story_bible.project_id
        unresolved = story_bible.unresolved_threads
        payoff_hint = str(unresolved[0]) if unresolved else "当前人物关系中的信息差"
        specs = [
            (
                "正面突破",
                f"主角直接尝试：{author_goal}",
                "目标遭遇显性阻力，迫使主角公开立场",
                "以行动成果兑现阶段目标",
                ["推进过快可能压缩人物反应空间"],
                ["提前展示阻力方的资源或底线"],
            ),
            (
                "代价交换",
                f"主角获得通往“{author_goal}”的机会，但必须承担新代价",
                "短期收益与长期损失不可兼得",
                "先抑后扬，让选择体现人物主动性",
                ["代价必须真实生效，不能下一幕取消"],
                ["在选择前呈现代价影响的重要对象"],
            ),
            (
                "信息反转",
                f"围绕“{author_goal}”揭示一条改变判断的新信息",
                "旧认知与新证据冲突，盟友动机受到质疑",
                f"回扣或变形利用伏笔：{payoff_hint}",
                ["新信息必须有前置线索，避免机械反转"],
                ["安排可回看验证的细节，但不直接揭底"],
            ),
        ]
        options = [
            make_model(
                PlotOption,
                {
                    "project_id": project_id,
                    "title": title,
                    "summary": summary,
                    "conflict": conflict,
                    "payoff": payoff,
                    "risks": risks,
                    "foreshadowing": foreshadowing,
                    "canon_risks": ["落笔前核对人物知情范围、能力边界与时间线位置"],
                },
            )
            for title, summary, conflict, payoff, risks, foreshadowing in specs
        ]
        return make_model(
            PlotPlan,
            {
                "project_id": project_id,
                "current_arc": current_summary,
                "arc_goal": author_goal,
                "conflict": "目标推进与既有阻力、人物代价之间的冲突",
                "stakes": "失败会失去行动窗口，并改变关键关系",
                "turning_points": [
                    "现状被打破",
                    "主角作出不可轻易撤销的选择",
                    "结果制造下一章的新问题",
                ],
                "climax_options": [
                    "公开对抗中以准备好的信息差逆转",
                    "完成目标但暴露更大威胁",
                    "主动放弃表面收益换取长期主动权",
                ],
                "foreshadowing_to_plant": ["阻力方能力边界", "选择代价的具体征兆"],
                "foreshadowing_to_payoff": [payoff_hint] if unresolved else [],
                "next_chapter_options": options,
                "bible_version": story_bible.version,
            },
        )

    async def aplan(self, *args: Any, **kwargs: Any) -> PlotPlan:
        baseline = self.plan(*args, **kwargs)
        if self.llm_provider is None:
            return baseline
        prompt = format_prompt(
            load_prompt("plot_planner"),
            {
                "story_bible": args[0] if args else kwargs.get("story_bible"),
                "current_summary": args[1] if len(args) > 1 else kwargs.get("current_summary"),
                "author_goal": args[2] if len(args) > 2 else kwargs.get("author_goal"),
                "retrieved_context": kwargs.get("retrieved_context", ""),
                "baseline": baseline,
            },
        )
        generated = await call_provider_overlay(
            self.llm_provider,
            prompt=prompt,
            baseline=baseline,
            preserve=(
                "id",
                "project_id",
                "created_at",
                "updated_at",
                "bible_version",
            ),
        )
        options: list[PlotOption] = []
        for raw in generated.next_chapter_options:
            if isinstance(raw, PlotOption):
                option = raw.model_copy(update={"project_id": baseline.project_id})
            elif isinstance(raw, dict):
                option = PlotOption.model_validate(
                    {"project_id": baseline.project_id, **raw},
                    extra="ignore",
                )
            else:
                continue
            options.append(option)
        existing_titles = {option.title for option in options}
        for fallback in baseline.next_chapter_options:
            if len(options) >= 3:
                break
            if isinstance(fallback, PlotOption) and fallback.title not in existing_titles:
                options.append(fallback)
                existing_titles.add(fallback.title)
        return generated.model_copy(
            update={
                "project_id": baseline.project_id,
                "bible_version": baseline.bible_version,
                "next_chapter_options": options,
            }
        )

    async def run(self, *args: Any, **kwargs: Any) -> PlotPlan:
        return await self.aplan(*args, **kwargs)
