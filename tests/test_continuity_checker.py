from novel_harness.agents import ContinuityChecker
from novel_harness.models import CharacterProfile, StoryBible


def test_continuity_checker_finds_age_conflict() -> None:
    character = CharacterProfile(
        project_id="project-1",
        name="林川",
        role="主角",
        age=20,
    )
    bible = StoryBible(project_id="project-1", characters=[character])
    issues = ContinuityChecker().check("林川今年已经三十岁。", bible)
    assert any(issue.category == "character" for issue in issues)
    assert any(issue.severity == "error" for issue in issues)
