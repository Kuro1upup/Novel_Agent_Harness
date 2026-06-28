"""Transport request and composite response models."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import DomainModel
from .generation import ContinuityIssue, FactRisk, GenerationResult
from .memory import MemoryConflict, MemorySearchHit
from .workflow import WorkflowEvent, WorkflowRun, WorkflowStep


class ProjectCreate(DomainModel):
    name: str = Field(min_length=1, max_length=255)
    genre: str = Field(min_length=1, max_length=100)
    sub_genre: str | None = None
    premise: str = ""
    target_audience: str = ""
    tone: str = ""


class ResearchRequest(DomainModel):
    topic: str = Field(min_length=1)
    historical_context: str = ""
    keywords: list[str] = Field(default_factory=list)


class PlotRequest(DomainModel):
    current: str = Field(min_length=1)
    goal: str = Field(min_length=1)


class WriteRequest(DomainModel):
    goal: str = Field(min_length=1)
    current: str = ""


class CheckRequest(DomainModel):
    draft: str = Field(min_length=1)


class WriteResponse(DomainModel):
    draft: GenerationResult
    continuity_issues: list[ContinuityIssue]
    fact_risks: list[FactRisk]
    originality: dict[str, float | int | bool | None]
    canon_patch_id: str


class CheckResponse(DomainModel):
    continuity_issues: list[ContinuityIssue]
    fact_risks: list[FactRisk]


class ErrorResponse(DomainModel):
    error: str
    message: str


class WorkflowCreateRequest(DomainModel):
    goal: str = Field(min_length=1)
    current: str = ""
    research_topic: str | None = None
    auto_approve: bool = False
    max_attempts: int = Field(default=3, ge=1, le=20)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class WorkflowApprovalRequest(DomainModel):
    decision: Literal["approve", "reject"]
    actor: str = Field(default="author", min_length=1, max_length=100)
    note: str = Field(default="", max_length=2000)


class WorkflowRetryRequest(DomainModel):
    from_step: str | None = Field(default=None, max_length=100)


class WorkflowRunDetail(DomainModel):
    run: WorkflowRun
    steps: list[WorkflowStep]
    events: list[WorkflowEvent]


class MemoryQueryRequest(DomainModel):
    query: str = Field(min_length=1)
    kinds: list[str] = Field(default_factory=list)
    limit: int = Field(default=10, ge=1, le=100)


class MemoryQueryResponse(DomainModel):
    revision: int
    hits: list[MemorySearchHit]
    conflicts: list[MemoryConflict] = Field(default_factory=list)


class MemoryInvalidateRequest(DomainModel):
    reason: str = Field(min_length=1, max_length=2000)
