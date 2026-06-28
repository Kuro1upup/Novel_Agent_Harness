from novel_harness.agents import PlotPlanner
from novel_harness.models import StoryBible


def test_plot_planner_returns_three_options() -> None:
    bible = StoryBible(
        project_id="project-1",
        unresolved_threads=["失踪的密使"],
        world_summary="西汉长安",
    )
    plan = PlotPlanner().plan(bible, "主角抵达城门", "进入长安")
    assert len(plan.next_chapter_options) == 3
    assert all(option.conflict for option in plan.next_chapter_options)
    assert all(option.risks for option in plan.next_chapter_options)
    assert all(option.foreshadowing for option in plan.next_chapter_options)
