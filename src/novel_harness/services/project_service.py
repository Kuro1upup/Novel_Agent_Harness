"""Project application service."""

from __future__ import annotations

from sqlalchemy.orm import Session

from novel_harness.exceptions import ProjectArchivedError
from novel_harness.models import ManuscriptVolume, NovelProject, StoryBible, utc_now
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
        self.repositories.manuscript_volumes.add(
            ManuscriptVolume(project_id=project.id, title="第一卷")
        )
        return project

    def get(self, project_id: str, *, include_archived: bool = True) -> NovelProject:
        return self.repositories.projects.require(
            project_id,
            include_archived=include_archived,
        )

    def list(self, *, include_archived: bool = False) -> list[NovelProject]:
        return self.repositories.projects.list(include_archived=include_archived)

    def update(self, project_id: str, **changes: object) -> NovelProject:
        project = self.repositories.projects.require(project_id, include_archived=True)
        allowed = {
            "name",
            "genre",
            "sub_genre",
            "premise",
            "target_audience",
            "tone",
            "status",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"unsupported project fields: {sorted(unknown)}")
        if project.status == "archived" and changes != {"status": "active"}:
            raise ProjectArchivedError(
                f"Novel project {project_id!r} must be restored before it can be edited"
            )
        values = {key: value for key, value in changes.items() if key in allowed}
        for required in ("name", "genre"):
            if required in values and values[required] is None:
                raise ValueError(f"{required} cannot be null")
        if "status" in values:
            values["archived_at"] = utc_now() if values["status"] == "archived" else None
        if not values:
            return project
        return self.repositories.projects.update(project.model_copy(update=values))
