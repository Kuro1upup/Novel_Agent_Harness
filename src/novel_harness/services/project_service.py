"""Project application service."""

from __future__ import annotations

from sqlalchemy.orm import Session

from novel_harness.models import NovelProject, StoryBible
from novel_harness.storage.repositories import Repositories


class ProjectService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repositories = Repositories(session)

    def create(
        self,
        *,
        owner_user_id: int = 0,
        name: str,
        genre: str,
        sub_genre: str | None = None,
        premise: str = "",
        target_audience: str = "",
        tone: str = "",
    ) -> NovelProject:
        project = NovelProject(
            owner_user_id=owner_user_id,
            name=name,
            genre=genre,
            sub_genre=sub_genre,
            premise=premise,
            target_audience=target_audience,
            tone=tone,
        )
        self.repositories.projects.add(project)
        self.repositories.story_bibles.add(StoryBible(project_id=project.id))
        return project

    def get(self, project_id: str) -> NovelProject:
        return self.repositories.projects.require(project_id)

    def list(self) -> list[NovelProject]:
        return self.repositories.projects.list()
