"""Repository implementations over SQLAlchemy sessions."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from hashlib import sha256
from typing import Any, Generic, TypeVar, cast

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from novel_harness.exceptions import ProjectArchivedError
from novel_harness.models import (
    AgentRun,
    CanonPatch,
    CharacterProfile,
    ContinuityIssue,
    Document,
    DocumentChunk,
    FactRisk,
    GenerationResult,
    ManuscriptChapter,
    ManuscriptVolume,
    MemoryConflict,
    MemoryRecord,
    MemoryState,
    NovelProject,
    PlotOption,
    PlotPlan,
    ResearchNote,
    SearchResult,
    StoryBible,
    StyleProfile,
    WorkflowEvent,
    WorkflowRun,
    WorkflowStep,
)
from novel_harness.models.base import ProjectResource, utc_now
from novel_harness.security import current_user_id

from .orm import (
    AgentRunORM,
    CanonPatchORM,
    CharacterProfileORM,
    ContinuityIssueORM,
    DocumentChunkORM,
    DocumentORM,
    FactRiskORM,
    GenerationResultORM,
    ManuscriptChapterORM,
    ManuscriptVolumeORM,
    MemoryConflictORM,
    MemoryRecordORM,
    NovelProjectORM,
    PlotOptionORM,
    PlotPlanORM,
    ProjectMemoryStateORM,
    ResearchNoteORM,
    SearchResultORM,
    StoryBibleORM,
    StoryBibleVersionORM,
    StyleProfileORM,
    WorkflowEventORM,
    WorkflowRunORM,
    WorkflowStepORM,
)

ModelT = TypeVar("ModelT", bound=ProjectResource)


class RepositoryError(RuntimeError):
    pass


class ResourceNotFoundError(RepositoryError):
    pass


class VersionConflictError(RepositoryError):
    pass


class ProjectRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, project: NovelProject) -> NovelProject:
        self.session.add(
            NovelProjectORM(
                id=project.id,
                owner_user_id=project.owner_user_id,
                name=project.name,
                genre=project.genre,
                sub_genre=project.sub_genre,
                premise=project.premise,
                target_audience=project.target_audience,
                tone=project.tone,
                status=project.status,
                archived_at=project.archived_at,
                created_at=project.created_at,
                updated_at=project.updated_at,
            )
        )
        self.session.flush()
        return project

    create = add

    def get(self, project_id: str) -> NovelProject | None:
        statement = select(NovelProjectORM).where(NovelProjectORM.id == project_id)
        owner_user_id = current_user_id()
        if owner_user_id is not None:
            statement = statement.where(NovelProjectORM.owner_user_id == owner_user_id)
        record = self.session.scalar(statement)
        return self._to_domain(record) if record is not None else None

    def require(
        self,
        project_id: str,
        *,
        include_archived: bool = False,
    ) -> NovelProject:
        project = self.get(project_id)
        if project is None:
            raise ResourceNotFoundError(f"Novel project {project_id!r} was not found")
        if project.status == "archived" and not include_archived:
            raise ProjectArchivedError(f"Novel project {project_id!r} is archived")
        return project

    def list(
        self,
        *,
        include_archived: bool = False,
        offset: int = 0,
        limit: int = 100,
    ) -> list[NovelProject]:
        statement = (
            select(NovelProjectORM).order_by(NovelProjectORM.created_at).offset(offset).limit(limit)
        )
        if not include_archived:
            statement = statement.where(NovelProjectORM.status == "active")
        owner_user_id = current_user_id()
        if owner_user_id is not None:
            statement = statement.where(NovelProjectORM.owner_user_id == owner_user_id)
        return [self._to_domain(item) for item in self.session.scalars(statement)]

    def update(self, project: NovelProject) -> NovelProject:
        statement = select(NovelProjectORM).where(NovelProjectORM.id == project.id)
        owner_user_id = current_user_id()
        if owner_user_id is not None:
            statement = statement.where(NovelProjectORM.owner_user_id == owner_user_id)
        record = self.session.scalar(statement)
        if record is None:
            raise ResourceNotFoundError(f"Novel project {project.id!r} was not found")
        project.updated_at = utc_now()
        for field in (
            "name",
            "genre",
            "sub_genre",
            "premise",
            "target_audience",
            "tone",
            "status",
            "archived_at",
            "updated_at",
        ):
            setattr(record, field, getattr(project, field))
        self.session.flush()
        return project

    def delete(self, project_id: str) -> bool:
        statement = delete(NovelProjectORM).where(NovelProjectORM.id == project_id)
        owner_user_id = current_user_id()
        if owner_user_id is not None:
            statement = statement.where(NovelProjectORM.owner_user_id == owner_user_id)
        result = self.session.execute(statement)
        return bool(cast(CursorResult[Any], result).rowcount)

    @staticmethod
    def _to_domain(record: NovelProjectORM) -> NovelProject:
        return NovelProject.model_validate(record)


class JsonRepository(Generic[ModelT]):
    """Base CRUD repository for entities whose canonical shape is JSON."""

    domain_model: type[ModelT]
    orm_model: type[Any]

    def __init__(self, session: Session) -> None:
        self.session = session

    def _extra_values(self, model: ModelT) -> dict[str, Any]:
        return {}

    def _record_values(self, model: ModelT) -> dict[str, Any]:
        return {
            "id": model.id,
            "project_id": model.project_id,
            "payload": model.model_dump(mode="json"),
            "created_at": model.created_at,
            "updated_at": model.updated_at,
            **self._extra_values(model),
        }

    def add(self, model: ModelT) -> ModelT:
        self.session.add(self.orm_model(**self._record_values(model)))
        self.session.flush()
        return model

    create = add

    def get(self, resource_id: str) -> ModelT | None:
        statement = select(self.orm_model).where(self.orm_model.id == resource_id)
        statement = self._scope_to_owner(statement)
        record = self.session.scalar(statement)
        if record is None:
            return None
        return self.domain_model.model_validate(record.payload)

    def require(self, resource_id: str) -> ModelT:
        model = self.get(resource_id)
        if model is None:
            raise ResourceNotFoundError(
                f"{self.domain_model.__name__} {resource_id!r} was not found"
            )
        return model

    def list(self, project_id: str, *, offset: int = 0, limit: int = 100) -> list[ModelT]:
        statement = (
            select(self.orm_model)
            .where(self.orm_model.project_id == project_id)
            .order_by(self.orm_model.created_at)
            .offset(offset)
            .limit(limit)
        )
        statement = self._scope_to_owner(statement)
        return [
            self.domain_model.model_validate(record.payload)
            for record in self.session.scalars(statement)
        ]

    def update(self, model: ModelT) -> ModelT:
        statement = select(self.orm_model).where(self.orm_model.id == model.id)
        statement = self._scope_to_owner(statement)
        record = self.session.scalar(statement)
        if record is None:
            raise ResourceNotFoundError(f"{self.domain_model.__name__} {model.id!r} was not found")
        if record.project_id != model.project_id:
            raise RepositoryError("A resource cannot be moved between projects")
        model.updated_at = utc_now()
        values = self._record_values(model)
        values.pop("id", None)
        values.pop("project_id", None)
        for key, value in values.items():
            setattr(record, key, value)
        self.session.flush()
        return model

    def delete(self, resource_id: str) -> bool:
        statement = delete(self.orm_model).where(self.orm_model.id == resource_id)
        owner_user_id = current_user_id()
        if owner_user_id is not None:
            owned_projects = select(NovelProjectORM.id).where(
                NovelProjectORM.owner_user_id == owner_user_id
            )
            statement = statement.where(self.orm_model.project_id.in_(owned_projects))
        result = self.session.execute(statement)
        return bool(cast(CursorResult[Any], result).rowcount)

    def _scope_to_owner(self, statement: Any) -> Any:
        owner_user_id = current_user_id()
        if owner_user_id is None:
            return statement
        return statement.join(
            NovelProjectORM,
            self.orm_model.project_id == NovelProjectORM.id,
        ).where(
            NovelProjectORM.owner_user_id == owner_user_id,
            NovelProjectORM.status == "active",
        )


class StyleProfileRepository(JsonRepository[StyleProfile]):
    domain_model = StyleProfile
    orm_model = StyleProfileORM

    def _extra_values(self, model: StyleProfile) -> dict[str, Any]:
        return {"version": model.version}


class CharacterRepository(JsonRepository[CharacterProfile]):
    domain_model = CharacterProfile
    orm_model = CharacterProfileORM

    def _extra_values(self, model: CharacterProfile) -> dict[str, Any]:
        return {"name": model.name, "role": model.role}


class ResearchRepository(JsonRepository[ResearchNote]):
    domain_model = ResearchNote
    orm_model = ResearchNoteORM

    def _extra_values(self, model: ResearchNote) -> dict[str, Any]:
        return {
            "topic": model.topic,
            "query": model.query,
            "source_url": str(model.source_url),
            "credibility_score": model.credibility_score,
        }


class SearchResultRepository(JsonRepository[SearchResult]):
    domain_model = SearchResult
    orm_model = SearchResultORM

    def _extra_values(self, model: SearchResult) -> dict[str, Any]:
        return {
            "query": model.query,
            "url_hash": sha256(str(model.url).encode()).hexdigest(),
        }


class StoryBibleRepository(JsonRepository[StoryBible]):
    domain_model = StoryBible
    orm_model = StoryBibleORM

    def _extra_values(self, model: StoryBible) -> dict[str, Any]:
        return {"version": model.version}

    def add(self, model: StoryBible) -> StoryBible:
        super().add(model)
        self.session.add(
            StoryBibleVersionORM(
                bible_id=model.id,
                project_id=model.project_id,
                version=model.version,
                payload=model.model_dump(mode="json"),
                created_at=model.updated_at,
            )
        )
        self.session.flush()
        return model

    create = add

    def get_for_project(self, project_id: str) -> StoryBible | None:
        record = self.session.scalar(
            select(StoryBibleORM).where(StoryBibleORM.project_id == project_id)
        )
        return StoryBible.model_validate(record.payload) if record is not None else None

    def update_versioned(self, bible: StoryBible, *, expected_version: int) -> StoryBible:
        """Atomically replace canon if its version still matches the caller."""

        if bible.version not in (expected_version, expected_version + 1):
            raise ValueError("The supplied StoryBible has an invalid target version")
        updated = bible.model_copy(
            update={"version": expected_version + 1, "updated_at": utc_now()}
        )
        payload = updated.model_dump(mode="json")
        result = self.session.execute(
            update(StoryBibleORM)
            .where(
                StoryBibleORM.id == bible.id,
                StoryBibleORM.project_id == bible.project_id,
                StoryBibleORM.version == expected_version,
            )
            .values(
                payload=payload,
                version=updated.version,
                updated_at=updated.updated_at,
            )
        )
        if cast(CursorResult[Any], result).rowcount != 1:
            raise VersionConflictError(
                f"Story Bible version {expected_version} is no longer current"
            )
        self.session.add(
            StoryBibleVersionORM(
                bible_id=updated.id,
                project_id=updated.project_id,
                version=updated.version,
                payload=payload,
                created_at=updated.updated_at,
            )
        )
        self.session.flush()
        return updated

    def update(self, model: StoryBible) -> StoryBible:
        return self.update_versioned(model, expected_version=model.version)

    def get_version(self, bible_id: str, version: int) -> StoryBible | None:
        record = self.session.scalar(
            select(StoryBibleVersionORM).where(
                StoryBibleVersionORM.bible_id == bible_id,
                StoryBibleVersionORM.version == version,
            )
        )
        return StoryBible.model_validate(record.payload) if record else None


class PlotPlanRepository(JsonRepository[PlotPlan]):
    domain_model = PlotPlan
    orm_model = PlotPlanORM

    def _extra_values(self, model: PlotPlan) -> dict[str, Any]:
        return {
            "bible_version": model.bible_version,
            "current_arc": model.current_arc,
        }


class PlotOptionRepository(JsonRepository[PlotOption]):
    domain_model = PlotOption
    orm_model = PlotOptionORM

    def _extra_values(self, model: PlotOption) -> dict[str, Any]:
        return {"plot_plan_id": model.plot_plan_id, "title": model.title}

    def list_for_plan(self, plot_plan_id: str) -> list[PlotOption]:
        statement = (
            select(PlotOptionORM)
            .where(PlotOptionORM.plot_plan_id == plot_plan_id)
            .order_by(PlotOptionORM.created_at)
        )
        return [
            PlotOption.model_validate(record.payload) for record in self.session.scalars(statement)
        ]


class GenerationRepository(JsonRepository[GenerationResult]):
    domain_model = GenerationResult
    orm_model = GenerationResultORM

    def _record_values(self, model: GenerationResult) -> dict[str, Any]:
        if model.body and not model.object_key:
            raise RepositoryError(
                "Generated chapter bodies must be uploaded to object storage first"
            )
        values = super()._record_values(model)
        # MySQL contains metadata only. The authoritative chapter body lives in
        # MinIO and is retrieved by the generation service using object_key.
        values["payload"] = model.model_copy(update={"body": ""}).model_dump(mode="json")
        return values

    def _extra_values(self, model: GenerationResult) -> dict[str, Any]:
        return {
            "status": model.status,
            "object_key": model.object_key,
            "bible_version": model.bible_version,
            "plot_plan_id": model.plot_plan_id,
            "selected_option_id": model.selected_option_id,
            "parent_draft_id": model.parent_draft_id,
            "revision_number": model.revision_number,
        }

    def list_by_status(
        self,
        project_id: str,
        *,
        status: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[GenerationResult]:
        statement = select(GenerationResultORM).where(GenerationResultORM.project_id == project_id)
        if status:
            statement = statement.where(GenerationResultORM.status == status)
        statement = (
            statement.order_by(GenerationResultORM.created_at.desc()).offset(offset).limit(limit)
        )
        return [
            GenerationResult.model_validate(record.payload)
            for record in self.session.scalars(statement)
        ]


class ManuscriptVolumeRepository(JsonRepository[ManuscriptVolume]):
    domain_model = ManuscriptVolume
    orm_model = ManuscriptVolumeORM

    def _extra_values(self, model: ManuscriptVolume) -> dict[str, Any]:
        return {
            "title": model.title,
            "position": model.position,
            "status": model.status,
        }

    def list_ordered(
        self,
        project_id: str,
        *,
        include_archived: bool = False,
    ) -> list[ManuscriptVolume]:
        statement = select(ManuscriptVolumeORM).where(ManuscriptVolumeORM.project_id == project_id)
        if not include_archived:
            statement = statement.where(ManuscriptVolumeORM.status == "active")
        statement = statement.order_by(
            ManuscriptVolumeORM.position,
            ManuscriptVolumeORM.created_at,
        )
        statement = self._scope_to_owner(statement)
        return [
            ManuscriptVolume.model_validate(record.payload)
            for record in self.session.scalars(statement)
        ]

    def next_position(self, project_id: str) -> int:
        value = self.session.scalar(
            select(func.max(ManuscriptVolumeORM.position)).where(
                ManuscriptVolumeORM.project_id == project_id
            )
        )
        return int(value or 0) + 1


class ManuscriptChapterRepository(JsonRepository[ManuscriptChapter]):
    domain_model = ManuscriptChapter
    orm_model = ManuscriptChapterORM

    def _extra_values(self, model: ManuscriptChapter) -> dict[str, Any]:
        return {
            "volume_id": model.volume_id,
            "title": model.title,
            "position": model.position,
            "status": model.status,
            "draft_id": model.draft_id,
        }

    def list_ordered(
        self,
        project_id: str,
        *,
        volume_id: str | None = None,
    ) -> list[ManuscriptChapter]:
        statement = select(ManuscriptChapterORM).where(
            ManuscriptChapterORM.project_id == project_id
        )
        if volume_id is not None:
            statement = statement.where(ManuscriptChapterORM.volume_id == volume_id)
        statement = statement.order_by(
            ManuscriptChapterORM.volume_id,
            ManuscriptChapterORM.position,
            ManuscriptChapterORM.created_at,
        )
        statement = self._scope_to_owner(statement)
        return [
            ManuscriptChapter.model_validate(record.payload)
            for record in self.session.scalars(statement)
        ]

    def next_position(self, project_id: str, volume_id: str) -> int:
        value = self.session.scalar(
            select(func.max(ManuscriptChapterORM.position)).where(
                ManuscriptChapterORM.project_id == project_id,
                ManuscriptChapterORM.volume_id == volume_id,
            )
        )
        return int(value or 0) + 1

    def get_by_draft(self, draft_id: str) -> ManuscriptChapter | None:
        statement = select(ManuscriptChapterORM).where(ManuscriptChapterORM.draft_id == draft_id)
        statement = self._scope_to_owner(statement)
        record = self.session.scalar(statement)
        return ManuscriptChapter.model_validate(record.payload) if record else None


class ContinuityIssueRepository(JsonRepository[ContinuityIssue]):
    domain_model = ContinuityIssue
    orm_model = ContinuityIssueORM

    def _extra_values(self, model: ContinuityIssue) -> dict[str, Any]:
        return {
            "draft_id": model.draft_id,
            "category": model.category,
            "severity": model.severity,
        }

    def list_for_draft(self, draft_id: str) -> list[ContinuityIssue]:
        statement = (
            select(ContinuityIssueORM)
            .where(ContinuityIssueORM.draft_id == draft_id)
            .order_by(ContinuityIssueORM.created_at)
        )
        return [
            ContinuityIssue.model_validate(record.payload)
            for record in self.session.scalars(statement)
        ]


class FactRiskRepository(JsonRepository[FactRisk]):
    domain_model = FactRisk
    orm_model = FactRiskORM

    def _extra_values(self, model: FactRisk) -> dict[str, Any]:
        return {"draft_id": model.draft_id, "risk_level": model.risk_level}

    def list_for_draft(self, draft_id: str) -> list[FactRisk]:
        statement = (
            select(FactRiskORM)
            .where(FactRiskORM.draft_id == draft_id)
            .order_by(FactRiskORM.created_at)
        )
        return [
            FactRisk.model_validate(record.payload) for record in self.session.scalars(statement)
        ]


class DocumentRepository(JsonRepository[Document]):
    domain_model = Document
    orm_model = DocumentORM

    def _extra_values(self, model: Document) -> dict[str, Any]:
        return {
            "filename": model.filename,
            "mime_type": model.mime_type,
            "size_bytes": model.size_bytes,
            "content_hash": model.content_hash,
            "object_key": model.object_key,
            "status": model.status,
        }

    def get_by_hash(self, project_id: str, content_hash: str) -> Document | None:
        record = self.session.scalar(
            select(DocumentORM).where(
                DocumentORM.project_id == project_id,
                DocumentORM.content_hash == content_hash,
            )
        )
        return Document.model_validate(record.payload) if record else None


class DocumentChunkRepository(JsonRepository[DocumentChunk]):
    domain_model = DocumentChunk
    orm_model = DocumentChunkORM

    def _extra_values(self, model: DocumentChunk) -> dict[str, Any]:
        return {
            "document_id": model.document_id,
            "ordinal": model.ordinal,
            "content_hash": model.content_hash,
            "vector_id": model.vector_id,
            "status": model.status,
        }


class CanonPatchRepository(JsonRepository[CanonPatch]):
    domain_model = CanonPatch
    orm_model = CanonPatchORM

    def _extra_values(self, model: CanonPatch) -> dict[str, Any]:
        return {
            "draft_id": model.draft_id,
            "base_bible_version": model.base_bible_version,
            "accepted_bible_version": model.accepted_bible_version,
            "status": model.status,
        }

    def get_by_draft(self, draft_id: str) -> CanonPatch | None:
        statement = select(CanonPatchORM).where(CanonPatchORM.draft_id == draft_id)
        statement = self._scope_to_owner(statement)
        record = self.session.scalar(statement)
        return CanonPatch.model_validate(record.payload) if record else None


class AgentRunRepository(JsonRepository[AgentRun]):
    domain_model = AgentRun
    orm_model = AgentRunORM

    def _extra_values(self, model: AgentRun) -> dict[str, Any]:
        return {
            "agent_name": model.agent_name,
            "provider": model.provider,
            "status": model.status,
            "started_at": model.started_at,
            "finished_at": model.finished_at,
            "duration_ms": model.duration_ms,
            "model": model.model,
            "prompt_version": model.prompt_version,
            "prompt_tokens": model.prompt_tokens,
            "completion_tokens": model.completion_tokens,
            "estimated_cost": model.estimated_cost,
            "workflow_run_id": model.workflow_run_id,
            "trace_id": model.trace_id,
        }


class WorkflowRunRepository(JsonRepository[WorkflowRun]):
    domain_model = WorkflowRun
    orm_model = WorkflowRunORM

    def _extra_values(self, model: WorkflowRun) -> dict[str, Any]:
        return {
            "workflow_type": model.workflow_type,
            "idempotency_key": model.idempotency_key,
            "status": model.status,
            "current_step": model.current_step,
            "cancel_requested": model.cancel_requested,
            "available_at": model.available_at,
            "claimed_by": model.claimed_by,
            "claim_expires_at": model.claim_expires_at,
            "started_at": model.started_at,
            "finished_at": model.finished_at,
            "error": model.error,
        }

    def list_for_project(
        self,
        project_id: str,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[WorkflowRun]:
        statement = (
            select(WorkflowRunORM)
            .where(WorkflowRunORM.project_id == project_id)
            .order_by(WorkflowRunORM.created_at.desc())
            .limit(limit)
        )
        if status is not None:
            statement = statement.where(WorkflowRunORM.status == status)
        return [
            WorkflowRun.model_validate(record.payload) for record in self.session.scalars(statement)
        ]

    def get_by_idempotency_key(
        self,
        project_id: str,
        idempotency_key: str,
    ) -> WorkflowRun | None:
        record = self.session.scalar(
            select(WorkflowRunORM).where(
                WorkflowRunORM.project_id == project_id,
                WorkflowRunORM.idempotency_key == idempotency_key,
            )
        )
        return WorkflowRun.model_validate(record.payload) if record else None

    def require_for_update(self, run_id: str) -> WorkflowRun:
        statement = select(WorkflowRunORM).where(WorkflowRunORM.id == run_id)
        statement = self._scope_to_owner(statement)
        record = self.session.scalar(
            statement.with_for_update().execution_options(populate_existing=True)
        )
        if record is None:
            raise ResourceNotFoundError(f"WorkflowRun {run_id!r} was not found")
        return WorkflowRun.model_validate(record.payload)

    def claim_next(self, worker_id: str, *, lease_seconds: int) -> WorkflowRun | None:
        now = utc_now()
        statement = (
            select(WorkflowRunORM)
            .where(
                WorkflowRunORM.cancel_requested.is_(False),
                or_(
                    and_(
                        WorkflowRunORM.status == "queued",
                        WorkflowRunORM.available_at <= now,
                    ),
                    and_(
                        WorkflowRunORM.status == "running",
                        WorkflowRunORM.claim_expires_at.is_not(None),
                        WorkflowRunORM.claim_expires_at <= now,
                    ),
                ),
            )
            .order_by(WorkflowRunORM.available_at, WorkflowRunORM.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        record = self.session.scalar(statement)
        if record is None:
            return None
        existing = WorkflowRun.model_validate(record.payload)
        run = existing.model_copy(
            update={
                "status": "running",
                "claimed_by": worker_id,
                "claim_expires_at": now + timedelta(seconds=lease_seconds),
                "started_at": existing.started_at or now,
                "updated_at": now,
            }
        )
        values = self._record_values(run)
        values.pop("id", None)
        values.pop("project_id", None)
        for key, value in values.items():
            setattr(record, key, value)
        self.session.flush()
        return run


class WorkflowStepRepository(JsonRepository[WorkflowStep]):
    domain_model = WorkflowStep
    orm_model = WorkflowStepORM

    def _extra_values(self, model: WorkflowStep) -> dict[str, Any]:
        return {
            "run_id": model.run_id,
            "name": model.name,
            "position": model.position,
            "status": model.status,
            "attempt": model.attempt,
            "max_attempts": model.max_attempts,
            "requires_approval": model.requires_approval,
            "started_at": model.started_at,
            "finished_at": model.finished_at,
            "error": model.error,
        }

    def list_for_run(self, run_id: str) -> list[WorkflowStep]:
        statement = (
            select(WorkflowStepORM)
            .where(WorkflowStepORM.run_id == run_id)
            .order_by(WorkflowStepORM.position)
        )
        return [
            WorkflowStep.model_validate(record.payload)
            for record in self.session.scalars(statement)
        ]

    def get_for_run(self, run_id: str, name: str) -> WorkflowStep | None:
        record = self.session.scalar(
            select(WorkflowStepORM).where(
                WorkflowStepORM.run_id == run_id,
                WorkflowStepORM.name == name,
            )
        )
        return WorkflowStep.model_validate(record.payload) if record else None

    def get_for_run_for_update(self, run_id: str, name: str) -> WorkflowStep | None:
        record = self.session.scalar(
            select(WorkflowStepORM)
            .where(
                WorkflowStepORM.run_id == run_id,
                WorkflowStepORM.name == name,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return WorkflowStep.model_validate(record.payload) if record else None


class WorkflowEventRepository(JsonRepository[WorkflowEvent]):
    domain_model = WorkflowEvent
    orm_model = WorkflowEventORM

    def _extra_values(self, model: WorkflowEvent) -> dict[str, Any]:
        return {
            "run_id": model.run_id,
            "step_id": model.step_id,
            "sequence": model.sequence,
            "event_type": model.event_type,
        }

    def list_for_run(self, run_id: str) -> list[WorkflowEvent]:
        statement = (
            select(WorkflowEventORM)
            .where(WorkflowEventORM.run_id == run_id)
            .order_by(WorkflowEventORM.sequence)
        )
        return [
            WorkflowEvent.model_validate(record.payload)
            for record in self.session.scalars(statement)
        ]

    def next_sequence(self, run_id: str) -> int:
        value = self.session.scalar(
            select(func.max(WorkflowEventORM.sequence)).where(WorkflowEventORM.run_id == run_id)
        )
        return int(value or 0) + 1


class MemoryStateRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, project_id: str) -> MemoryState:
        record = self.session.get(ProjectMemoryStateORM, project_id)
        if record is None:
            return MemoryState(project_id=project_id)
        return MemoryState.model_validate(record)

    def bump(self, project_id: str) -> MemoryState:
        record = self.session.scalar(
            select(ProjectMemoryStateORM)
            .where(ProjectMemoryStateORM.project_id == project_id)
            .with_for_update()
        )
        now = utc_now()
        if record is None:
            record = ProjectMemoryStateORM(
                project_id=project_id,
                revision=1,
                updated_at=now,
            )
            self.session.add(record)
        else:
            record.revision += 1
            record.updated_at = now
        self.session.flush()
        return MemoryState.model_validate(record)


class MemoryRecordRepository(JsonRepository[MemoryRecord]):
    domain_model = MemoryRecord
    orm_model = MemoryRecordORM

    def _extra_values(self, model: MemoryRecord) -> dict[str, Any]:
        return {
            "kind": model.kind,
            "subject": model.subject,
            "predicate": model.predicate,
            "source_draft_id": model.source_draft_id,
            "canon_version": model.canon_version,
            "confidence": model.confidence,
            "source_hash": model.source_hash,
            "status": model.status,
        }

    def get_by_hash(self, project_id: str, source_hash: str) -> MemoryRecord | None:
        record = self.session.scalar(
            select(MemoryRecordORM).where(
                MemoryRecordORM.project_id == project_id,
                MemoryRecordORM.source_hash == source_hash,
            )
        )
        return MemoryRecord.model_validate(record.payload) if record else None

    def list_active(
        self,
        project_id: str,
        *,
        kinds: Sequence[str] | None = None,
        limit: int = 5000,
    ) -> list[MemoryRecord]:
        statement = (
            select(MemoryRecordORM)
            .where(
                MemoryRecordORM.project_id == project_id,
                MemoryRecordORM.status == "active",
            )
            .order_by(
                MemoryRecordORM.canon_version.desc(),
                MemoryRecordORM.created_at.desc(),
            )
            .limit(limit)
        )
        if kinds:
            statement = statement.where(MemoryRecordORM.kind.in_(kinds))
        return [
            MemoryRecord.model_validate(record.payload)
            for record in self.session.scalars(statement)
        ]

    def list_for_draft(self, draft_id: str) -> list[MemoryRecord]:
        records = self.session.scalars(
            select(MemoryRecordORM)
            .where(MemoryRecordORM.source_draft_id == draft_id)
            .order_by(MemoryRecordORM.created_at)
        )
        return [MemoryRecord.model_validate(record.payload) for record in records]

    def delete_for_project(self, project_id: str) -> int:
        result = self.session.execute(
            delete(MemoryRecordORM).where(MemoryRecordORM.project_id == project_id)
        )
        return int(cast(CursorResult[Any], result).rowcount or 0)


class MemoryConflictRepository(JsonRepository[MemoryConflict]):
    domain_model = MemoryConflict
    orm_model = MemoryConflictORM

    def _extra_values(self, model: MemoryConflict) -> dict[str, Any]:
        return {
            "run_id": model.run_id,
            "severity": model.severity,
            "category": model.category,
            "resolved": model.resolved,
        }


class Repositories:
    """Convenient repository registry for one SQLAlchemy unit of work."""

    def __init__(self, session: Session) -> None:
        self.projects = ProjectRepository(session)
        self.styles = StyleProfileRepository(session)
        self.characters = CharacterRepository(session)
        self.research = ResearchRepository(session)
        self.search_results = SearchResultRepository(session)
        self.story_bibles = StoryBibleRepository(session)
        self.plot_plans = PlotPlanRepository(session)
        self.plot_options = PlotOptionRepository(session)
        self.generations = GenerationRepository(session)
        self.manuscript_volumes = ManuscriptVolumeRepository(session)
        self.manuscript_chapters = ManuscriptChapterRepository(session)
        self.continuity_issues = ContinuityIssueRepository(session)
        self.fact_risks = FactRiskRepository(session)
        self.documents = DocumentRepository(session)
        self.document_chunks = DocumentChunkRepository(session)
        self.canon_patches = CanonPatchRepository(session)
        self.agent_runs = AgentRunRepository(session)
        self.workflow_runs = WorkflowRunRepository(session)
        self.workflow_steps = WorkflowStepRepository(session)
        self.workflow_events = WorkflowEventRepository(session)
        self.memory_states = MemoryStateRepository(session)
        self.memories = MemoryRecordRepository(session)
        self.memory_conflicts = MemoryConflictRepository(session)
