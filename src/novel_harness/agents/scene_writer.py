"""Original scene drafting constrained by canon and sourced research."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from novel_harness.models.generation import GenerationResult
from novel_harness.models.plot import PlotPlan
from novel_harness.models.research import ResearchNote
from novel_harness.models.story_bible import StoryBible
from novel_harness.models.style import StyleProfile

from ._base import (
    as_dict,
    call_provider_overlay,
    format_prompt,
    load_prompt,
    make_model,
    unique_strings,
)


class SceneWriter:
    def __init__(self, llm_provider: Any | None = None) -> None:
        self.llm_provider = llm_provider

    def write(
        self,
        style_profile: StyleProfile,
        story_bible: StoryBible,
        plot_plan: PlotPlan,
        research_notes: Sequence[ResearchNote],
        scene_goal: str,
        *,
        project_id: str | None = None,
        retrieved_context: str = "",
    ) -> GenerationResult:
        if not scene_goal.strip():
            raise ValueError("scene goal is required")
        project_id = project_id or story_bible.project_id
        characters = [
            str(as_dict(character).get("name", ""))
            for character in story_bible.characters
            if as_dict(character).get("name")
        ]
        protagonist = characters[0] if characters else "主角"
        option = plot_plan.next_chapter_options[0] if plot_plan.next_chapter_options else None
        conflict = (
            getattr(option, "conflict", "")
            if option is not None and not isinstance(option, dict)
            else (option or {}).get("conflict", "")
        )
        conflict = conflict or plot_plan.conflict or "计划遭遇了意料之外的阻力"
        research_detail = ""
        source_urls: list[str] = []
        research_gaps: list[str] = []
        usable_notes = [
            note
            for note in research_notes
            if note.source_type != "mock"
            and note.credibility_score >= 0.5
            and note.verification_status in {"fetched", "corroborated"}
        ]
        if usable_notes:
            for note in usable_notes:
                source_urls.append(str(note.source_url))
            first_facts = [
                evidence.text for evidence in usable_notes[0].evidence_snippets
            ] or usable_notes[0].extracted_facts
            if first_facts:
                research_detail = (
                    f"临行前，{protagonist}再次核对手中的记录。"
                    f"其中一条细节写着：{first_facts[0]} "
                    "他没有立刻把它当作定论，只把它列为需要验证的线索。"
                )
        else:
            research_gaps.append(f"核验场景目标涉及的现实事实：{scene_goal}")

        body = "\n\n".join(
            [
                f"{protagonist}抵达约定地点时，没有急着迈出下一步。",
                (
                    f"他此行只有一个明确目标：{scene_goal}。"
                    f"然而，{conflict}。周围人的反应比语言更快——视线短暂交错，"
                    "原本畅通的路径也在几句话之间变得狭窄。"
                ),
                research_detail
                or (
                    f"{protagonist}没有凭空猜测。他先确认能看到、能听到的事实，"
                    "再把无法判断的部分留给之后调查。"
                ),
                (
                    "“先按我们确认过的做。”他说。\n\n"
                    "这不是退让。相反，他主动缩小了眼前的选择，把对方必须回应的"
                    "问题摆到了明处。沉默持续片刻，第一道阻力终于露出边界。"
                ),
                (
                    f"{protagonist}没有在此刻追求彻底解决。他拿到一个能够推进"
                    f"“{plot_plan.arc_goal or scene_goal}”的新支点，同时也清楚看见："
                    "下一次选择会有真实代价。"
                ),
            ]
        )
        factual_basis = (
            f"使用 {len(usable_notes)} 条可追溯研究记录；正文将资料作为待核验线索呈现。"
            if usable_notes
            else "没有可信的外部事实资料；Mock 结果未作为事实使用，涉及现实细节的部分需进一步研究。"
        )
        return make_model(
            GenerationResult,
            {
                "project_id": project_id,
                "body": body,
                "creative_notes": (
                    f"采用{style_profile.narrative_pov or '限定视角'}，"
                    f"围绕“{scene_goal}”组织目标—阻力—选择—后果；"
                    "仅遵循抽象风格参数，未复用输入样本文句。"
                ),
                "factual_basis_summary": factual_basis,
                "source_urls": unique_strings(source_urls),
                "research_gaps": research_gaps,
                "bible_version": story_bible.version,
            },
        )

    async def awrite(self, *args: Any, **kwargs: Any) -> GenerationResult:
        baseline = self.write(*args, **kwargs)
        if self.llm_provider is None:
            return baseline
        prompt = format_prompt(
            load_prompt("scene_writer"),
            {
                "style_profile": args[0] if args else kwargs.get("style_profile"),
                "story_bible": args[1] if len(args) > 1 else kwargs.get("story_bible"),
                "plot_plan": args[2] if len(args) > 2 else kwargs.get("plot_plan"),
                "research_notes": args[3] if len(args) > 3 else kwargs.get("research_notes"),
                "scene_goal": args[4] if len(args) > 4 else kwargs.get("scene_goal"),
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
                "object_key",
                "status",
                "retrieval_query",
                "context_sources",
            ),
        )
        allowed_urls = {str(url) for url in baseline.source_urls}
        return generated.model_copy(
            update={
                "project_id": baseline.project_id,
                "bible_version": baseline.bible_version,
                "source_urls": [url for url in generated.source_urls if str(url) in allowed_urls],
            }
        )

    async def run(self, *args: Any, **kwargs: Any) -> GenerationResult:
        return await self.awrite(*args, **kwargs)
