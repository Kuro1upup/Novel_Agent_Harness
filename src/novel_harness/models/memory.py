"""Long-form narrative memory and consistency models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from .base import DomainModel, ProjectResource, utc_now

MemoryKind = Literal[
    "chapter_summary",
    "character_state",
    "location_state",
    "item_ownership",
    "relationship",
    "event",
    "knowledge",
    "foreshadowing",
]


class MemoryCandidate(DomainModel):
    kind: MemoryKind
    subject: str = Field(min_length=1, max_length=255)
    predicate: str = Field(default="", max_length=255)
    value: str = Field(default="", max_length=2000)
    statement: str = Field(min_length=1, max_length=2000)
    story_time: str = Field(default="", max_length=255)
    aliases: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0, le=1)


class MemoryExtraction(DomainModel):
    summary: str = Field(min_length=1, max_length=2000)
    memories: list[MemoryCandidate] = Field(default_factory=list, max_length=200)


class MemoryRecord(ProjectResource):
    kind: MemoryKind
    subject: str = Field(min_length=1, max_length=255)
    predicate: str = Field(default="", max_length=255)
    value: str = Field(default="", max_length=2000)
    statement: str = Field(min_length=1, max_length=2000)
    aliases: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    story_time: str = Field(default="", max_length=255)
    source_draft_id: str
    canon_version: int = Field(ge=1)
    confidence: float = Field(default=0.7, ge=0, le=1)
    source_hash: str = Field(min_length=64, max_length=64)
    status: Literal["active", "invalidated"] = "active"
    invalidated_reason: str = Field(default="", max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryState(DomainModel):
    project_id: str
    revision: int = Field(default=0, ge=0)
    updated_at: datetime = Field(default_factory=utc_now)


class MemorySearchHit(DomainModel):
    memory: MemoryRecord
    semantic_score: float = 0
    lexical_score: float = 0
    combined_score: float = 0


class MemoryConflict(ProjectResource):
    run_id: str | None = None
    query: str = ""
    severity: Literal["hard", "soft"] = "soft"
    category: Literal[
        "character",
        "location",
        "item",
        "timeline",
        "knowledge",
        "relationship",
        "other",
    ] = "other"
    description: str
    memory_ids: list[str] = Field(default_factory=list)
    suggestion: str = ""
    status: Literal["open", "resolved", "ignored"] = "open"
    resolution_note: str = Field(default="", max_length=2000)
    resolved_at: datetime | None = None
    resolved: bool = False
