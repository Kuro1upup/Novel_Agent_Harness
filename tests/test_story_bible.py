from novel_harness.models import CharacterProfile, GenerationResult
from novel_harness.services import ProjectService, StoryBibleService


def test_story_bible_add_character_and_foreshadowing(session) -> None:
    project = ProjectService(session).create(name="长安旧梦", genre="历史")
    service = StoryBibleService(session)
    bible = service.add_character(
        project.id,
        CharacterProfile(
            project_id=project.id,
            name="林川",
            role="主角",
            age=20,
            motivation="寻找真相",
        ),
    )
    assert bible.version == 2
    bible = service.add_foreshadowing(project.id, "残缺的铜符", planted_at="第一章")
    assert bible.version == 3
    assert bible.characters[0].name == "林川"
    assert bible.foreshadowing_items[0].status == "planted"


def test_canon_patch_requires_acceptance(session) -> None:
    project = ProjectService(session).create(name="测试", genre="玄幻")
    service = StoryBibleService(session)
    service.repositories.generations.add(
        GenerationResult(
            id="draft-1",
            project_id=project.id,
            body="",
            object_key="projects/test/draft.md",
        )
    )
    patch = service.create_patch(
        project.id,
        "draft-1",
        [{"op": "add_canon_event", "value": {"summary": "主角入城"}}],
    )
    assert not service.get(project.id).canon_events
    assert patch.status == "pending"
    accepted = service.accept_patch(patch.id)
    assert accepted.version == 2
    assert accepted.canon_events == [{"summary": "主角入城"}]
