"""SQLAlchemy ORM schema for relational metadata."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


LONG_TEXT = Text().with_variant(LONGTEXT(), "mysql")


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ProjectOwnedMixin(TimestampMixin):
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novel_projects.id", ondelete="CASCADE"), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class NovelProjectORM(TimestampMixin, Base):
    __tablename__ = "novel_projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    genre: Mapped[str] = mapped_column(String(100), nullable=False)
    sub_genre: Mapped[str | None] = mapped_column(String(100))
    premise: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="")
    target_audience: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tone: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StyleProfileORM(ProjectOwnedMixin, Base):
    __tablename__ = "style_profiles"

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (UniqueConstraint("project_id", "version", name="uq_style_project_version"),)


class CharacterProfileORM(ProjectOwnedMixin, Base):
    __tablename__ = "character_profiles"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(100), nullable=False, default="")

    __table_args__ = (Index("ix_character_project_name", "project_id", "name"),)


class ResearchNoteORM(ProjectOwnedMixin, Base):
    __tablename__ = "research_notes"

    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    credibility_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)

    __table_args__ = (Index("ix_research_project_topic", "project_id", "topic"),)


class SearchResultORM(ProjectOwnedMixin, Base):
    __tablename__ = "search_results"

    query: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "url_hash", name="uq_search_result_project_url_hash"),
    )


class StoryBibleORM(ProjectOwnedMixin, Base):
    __tablename__ = "story_bibles"

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("project_id", name="uq_story_bible_project"),
        Index("ix_story_bible_project_version", "project_id", "version"),
    )


class StoryBibleVersionORM(Base):
    """Immutable Story Bible snapshot for audit and rollback workflows."""

    __tablename__ = "story_bible_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bible_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("story_bibles.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novel_projects.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("bible_id", "version", name="uq_story_bible_snapshot_version"),
        Index("ix_bible_snapshot_project_version", "project_id", "version"),
    )


class PlotPlanORM(ProjectOwnedMixin, Base):
    __tablename__ = "plot_plans"

    bible_version: Mapped[int] = mapped_column(Integer, nullable=False)
    current_arc: Mapped[str] = mapped_column(String(255), nullable=False, default="")


class PlotOptionORM(ProjectOwnedMixin, Base):
    __tablename__ = "plot_options"

    plot_plan_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("plot_plans.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)


class GenerationResultORM(ProjectOwnedMixin, Base):
    __tablename__ = "generation_results"

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    object_key: Mapped[str | None] = mapped_column(String(1024))
    bible_version: Mapped[int] = mapped_column(Integer, nullable=False)
    plot_plan_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("plot_plans.id", ondelete="SET NULL")
    )
    selected_option_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("plot_options.id", ondelete="SET NULL")
    )
    parent_draft_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("generation_results.id", ondelete="SET NULL")
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (Index("ix_generation_project_status", "project_id", "status"),)


class ManuscriptVolumeORM(ProjectOwnedMixin, Base):
    __tablename__ = "manuscript_volumes"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

    __table_args__ = (
        Index("ix_manuscript_volume_project_position", "project_id", "position"),
        Index("ix_manuscript_volume_project_status", "project_id", "status"),
    )


class ManuscriptChapterORM(ProjectOwnedMixin, Base):
    __tablename__ = "manuscript_chapters"

    volume_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("manuscript_volumes.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="planned")
    draft_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("generation_results.id", ondelete="SET NULL"),
        unique=True,
    )

    __table_args__ = (
        Index(
            "ix_manuscript_chapter_volume_position",
            "project_id",
            "volume_id",
            "position",
        ),
        Index("ix_manuscript_chapter_project_status", "project_id", "status"),
    )


class ContinuityIssueORM(ProjectOwnedMixin, Base):
    __tablename__ = "continuity_issues"

    draft_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("generation_results.id", ondelete="CASCADE")
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)


class FactRiskORM(ProjectOwnedMixin, Base):
    __tablename__ = "fact_risks"

    draft_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("generation_results.id", ondelete="CASCADE")
    )
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)


class DocumentORM(ProjectOwnedMixin, Base):
    __tablename__ = "documents"

    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")

    __table_args__ = (
        UniqueConstraint("project_id", "content_hash", name="uq_document_project_content_hash"),
        Index("ix_document_project_status", "project_id", "status"),
    )


class DocumentChunkORM(ProjectOwnedMixin, Base):
    __tablename__ = "document_chunks"

    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    vector_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")

    __table_args__ = (
        UniqueConstraint("document_id", "ordinal", name="uq_document_chunk_ordinal"),
        Index("ix_chunk_project_vector", "project_id", "vector_id"),
    )


class CanonPatchORM(ProjectOwnedMixin, Base):
    __tablename__ = "canon_patches"

    draft_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("generation_results.id", ondelete="CASCADE"),
        nullable=False,
    )
    base_bible_version: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_bible_version: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")

    __table_args__ = (
        UniqueConstraint("draft_id", name="uq_canon_patch_draft"),
        Index("ix_canon_patch_project_status", "project_id", "status"),
    )


class AgentRunORM(ProjectOwnedMixin, Base):
    __tablename__ = "agent_runs"

    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    model: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    workflow_run_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("workflow_runs.id", ondelete="SET NULL"),
    )
    trace_id: Mapped[str] = mapped_column(String(36), nullable=False, default="")

    __table_args__ = (
        Index("ix_agent_run_project_agent", "project_id", "agent_name"),
        Index("ix_agent_run_project_status", "project_id", "status"),
        Index("ix_agent_run_trace", "trace_id"),
    )


class WorkflowRunORM(ProjectOwnedMixin, Base):
    __tablename__ = "workflow_runs"

    workflow_type: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    current_step: Mapped[str | None] = mapped_column(String(100))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_by: Mapped[str | None] = mapped_column(String(255))
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(LONG_TEXT)

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "idempotency_key",
            name="uq_workflow_run_project_idempotency",
        ),
        Index("ix_workflow_run_queue", "status", "available_at", "claim_expires_at"),
        Index("ix_workflow_run_project_status", "project_id", "status"),
    )


class WorkflowStepORM(ProjectOwnedMixin, Base):
    __tablename__ = "workflow_steps"

    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(LONG_TEXT)

    __table_args__ = (
        UniqueConstraint("run_id", "name", name="uq_workflow_step_run_name"),
        UniqueConstraint("run_id", "position", name="uq_workflow_step_run_position"),
        Index("ix_workflow_step_run_status", "run_id", "status"),
    )


class WorkflowEventORM(ProjectOwnedMixin, Base):
    __tablename__ = "workflow_events"

    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("workflow_steps.id", ondelete="SET NULL"),
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_workflow_event_run_sequence"),
        Index("ix_workflow_event_run_created", "run_id", "created_at"),
    )


class ProjectMemoryStateORM(Base):
    __tablename__ = "project_memory_states"

    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("novel_projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class MemoryRecordORM(ProjectOwnedMixin, Base):
    __tablename__ = "memory_records"

    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    predicate: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    source_draft_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("generation_results.id", ondelete="CASCADE"),
        nullable=False,
    )
    canon_version: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

    __table_args__ = (
        UniqueConstraint("project_id", "source_hash", name="uq_memory_project_source_hash"),
        Index("ix_memory_project_kind_subject", "project_id", "kind", "subject"),
        Index("ix_memory_project_status_version", "project_id", "status", "canon_version"),
    )


class MemoryConflictORM(ProjectOwnedMixin, Base):
    __tablename__ = "memory_conflicts"

    run_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("workflow_runs.id", ondelete="SET NULL"),
    )
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("ix_memory_conflict_project_severity", "project_id", "severity"),
        Index("ix_memory_conflict_run", "run_id"),
    )
