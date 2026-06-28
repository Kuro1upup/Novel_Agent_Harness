"""Persistent workflow run, step and event models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from .base import ProjectResource, utc_now

WorkflowRunStatus = Literal[
    "queued",
    "running",
    "waiting_approval",
    "succeeded",
    "failed",
    "cancelled",
]
WorkflowStepStatus = Literal[
    "pending",
    "running",
    "waiting_approval",
    "succeeded",
    "failed",
    "skipped",
]


class WorkflowRun(ProjectResource):
    workflow_type: Literal["chapter_generation"] = "chapter_generation"
    idempotency_key: str | None = Field(default=None, max_length=128)
    status: WorkflowRunStatus = "queued"
    parameters: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    current_step: str | None = None
    cancel_requested: bool = False
    available_at: datetime = Field(default_factory=utc_now)
    claimed_by: str | None = None
    claim_expires_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None


class WorkflowStep(ProjectResource):
    run_id: str
    name: str = Field(min_length=1, max_length=100)
    position: int = Field(ge=0)
    status: WorkflowStepStatus = "pending"
    attempt: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1, le=20)
    requires_approval: bool = False
    approval_decision: Literal["approved", "rejected"] | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None


class WorkflowEvent(ProjectResource):
    run_id: str
    step_id: str | None = None
    sequence: int = Field(ge=1)
    event_type: str = Field(min_length=1, max_length=100)
    data: dict[str, Any] = Field(default_factory=dict)
