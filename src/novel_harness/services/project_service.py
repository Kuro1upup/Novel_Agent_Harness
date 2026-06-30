"""Project application service."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_harness.exceptions import ProjectArchivedError
from novel_harness.models import ManuscriptVolume, NovelProject, StoryBible, utc_now
from novel_harness.storage.orm import (
    DocumentChunkORM,
    DocumentORM,
    GenerationResultORM,
    ResearchNoteORM,
)
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

    def delete(
        self,
        project_id: str,
        *,
        object_store: Any | None = None,
        vector_store: Any | None = None,
    ) -> bool:
        """Permanently delete a project and its external artifacts.

        The MySQL schema cascades project-owned relational rows. Before removing
        the project row, delete known MinIO objects and project-scoped vectors so
        a hard delete does not leave large orphaned artifacts behind.
        """

        project = self.repositories.projects.require(project_id, include_archived=True)
        object_keys = self._object_keys(project.id)
        if vector_store is not None:
            vector_store.delete(project_id=project.id)
        if object_store is not None:
            for key in object_keys:
                object_store.remove(key)
        return self.repositories.projects.delete(project.id)

    def _object_keys(self, project_id: str) -> tuple[str, ...]:
        keys: set[str] = set()
        payload_fields = (
            (GenerationResultORM, ("object_key",)),
            (DocumentORM, ("object_key", "parsed_object_key")),
            (DocumentChunkORM, ("object_key",)),
            (ResearchNoteORM, ("source_object_key",)),
        )
        for orm_model, fields in payload_fields:
            statement = select(orm_model.payload).where(orm_model.project_id == project_id)
            for payload in self.session.scalars(statement):
                for field in fields:
                    _add_key(keys, payload.get(field))

        return tuple(sorted(keys))


def _add_key(keys: set[str], key: str | None) -> None:
    if key:
        keys.add(key)
