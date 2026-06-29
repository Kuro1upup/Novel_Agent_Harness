"""Generation, review, and agent-run models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, HttpUrl

from .base import ProjectResource, utc_now


class ContextReference(ProjectResource):
    source_id: str
    source_type: str
    score: float
    source_url: HttpUrl | str | None = None
    content_hash: str = ""


class GenerationResult(ProjectResource):
    body: str
    creative_notes: str = ""
    factual_basis_summary: str = ""
    source_urls: list[HttpUrl | str] = Field(default_factory=list)
    research_gaps: list[str] = Field(default_factory=list)
    status: Literal["draft", "accepted", "rejected", "superseded"] = "draft"
    object_key: str | None = None
    bible_version: int = Field(default=1, ge=1)
    plot_plan_id: str | None = None
    selected_option_id: str | None = None
    chapter_id: str | None = None
    parent_draft_id: str | None = None
    revision_number: int = Field(default=1, ge=1)
    revision_instruction: str = ""
    retrieval_query: str = ""
    context_sources: list[ContextReference] = Field(default_factory=list)


class ContinuityIssue(ProjectResource):
    draft_id: str | None = None
    category: Literal[
        "character", "timeline", "world_rule", "foreshadowing", "motivation", "other"
    ] = "other"
    severity: Literal["info", "warning", "error"] = "warning"
    description: str
    evidence: str = ""
    suggestion: str = ""


class FactRisk(ProjectResource):
    draft_id: str | None = None
    claim: str
    assessment: Literal["确定", "可能有问题", "不确定"] = "不确定"
    risk_level: Literal["low", "medium", "high", "unknown"] = "unknown"
    reason: str = ""
    source_urls: list[HttpUrl | str] = Field(default_factory=list)
    suggestion: str = ""


class AgentRun(ProjectResource):
    agent_name: str
    provider: str
    status: Literal["pending", "running", "succeeded", "failed"] = "pending"
    input_summary: str = ""
    output_summary: str = ""
    error_type: str | None = None
    error_message: str | None = None
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    model: str = ""
    prompt_version: str = ""
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    estimated_cost: float = Field(default=0.0, ge=0)
    workflow_run_id: str | None = None
    trace_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
