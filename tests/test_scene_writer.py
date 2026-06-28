from novel_harness.agents import SceneWriter
from novel_harness.models import PlotPlan, ResearchNote, StoryBible, StyleProfile


def test_scene_writer_does_not_treat_mock_search_as_fact() -> None:
    project_id = "project-1"
    result = SceneWriter().write(
        StyleProfile(project_id=project_id),
        StoryBible(project_id=project_id),
        PlotPlan(project_id=project_id, arc_goal="入城"),
        [
            ResearchNote(
                project_id=project_id,
                topic="测试",
                query="测试",
                source_title="Mock",
                source_url="mock://search/result-1",
                source_type="mock",
                credibility_score=0,
                extracted_facts=["虚构的 Mock 事实"],
            )
        ],
        "进入长安",
    )
    assert "虚构的 Mock 事实" not in result.body
    assert "Mock 结果未作为事实使用" in result.factual_basis_summary
    assert result.research_gaps
