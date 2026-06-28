import pytest

from novel_harness.agents import ResearchAgent
from novel_harness.providers.search import MockSearchProvider


@pytest.mark.asyncio
async def test_research_agent_marks_mock_as_unverified() -> None:
    notes = await ResearchAgent(MockSearchProvider()).research(
        "历史", "西汉", ["长安"], "市井生活", project_id="project-1"
    )
    assert notes
    assert all(note.project_id == "project-1" for note in notes)
    assert all(note.credibility_score == 0 for note in notes)
    assert all(str(note.source_url).startswith("mock:") for note in notes)
