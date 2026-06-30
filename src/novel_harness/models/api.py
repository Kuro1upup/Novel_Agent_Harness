"""Transport request and composite response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from .base import DomainModel
from .character import CharacterProfile
from .creative import ForeshadowingProposal, WorldbuildingProposal
from .generation import ContinuityIssue, FactRisk, GenerationResult
from .manuscript import ManuscriptChapter, ManuscriptVolume
from .memory import MemoryConflict, MemorySearchHit
from .story_bible import StoryBible, TimelineEvent
from .workflow import WorkflowEvent, WorkflowRun, WorkflowStep


class ProjectCreate(DomainModel):
    name: str = Field(min_length=1, max_length=255)
    genre: str = Field(min_length=1, max_length=100)
    sub_genre: str | None = None
    premise: str = ""
    target_audience: str = ""
    tone: str = ""


class ProjectUpdate(DomainModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    genre: str | None = Field(default=None, min_length=1, max_length=100)
    sub_genre: str | None = Field(default=None, max_length=100)
    premise: str | None = None
    target_audience: str | None = None
    tone: str | None = None
    status: Literal["active", "archived"] | None = None


class VolumeCreate(DomainModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    position: int | None = Field(default=None, ge=1)


class VolumeUpdate(DomainModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    position: int | None = Field(default=None, ge=1)
    status: Literal["active", "archived"] | None = None


class ChapterCreate(DomainModel):
    volume_id: str
    title: str = Field(min_length=1, max_length=255)
    summary: str = Field(default="", max_length=5000)
    position: int | None = Field(default=None, ge=1)
    draft_id: str | None = None
    status: Literal["planned", "drafting", "accepted", "completed"] | None = None


class ChapterUpdate(DomainModel):
    volume_id: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    summary: str | None = Field(default=None, max_length=5000)
    position: int | None = Field(default=None, ge=1)
    draft_id: str | None = None
    status: Literal["planned", "drafting", "accepted", "completed"] | None = None


class ManuscriptOutline(DomainModel):
    volumes: list[ManuscriptVolume]
    chapters: list[ManuscriptChapter]


class ManuscriptReorderRequest(DomainModel):
    ordered_ids: list[str] = Field(min_length=1)


class ManuscriptPreview(DomainModel):
    volume_count: int = Field(ge=0)
    chapter_count: int = Field(ge=0)
    exportable_chapter_count: int = Field(ge=0)
    total_characters: int = Field(ge=0)
    total_paragraphs: int = Field(ge=0)


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
    plot_plan_id: str | None = None
    selected_option_id: str | None = None
    chapter_id: str | None = None


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
    chapter_id: str | None = None
    auto_approve: bool = False
    max_attempts: int = Field(default=3, ge=1, le=20)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class WorkflowApprovalRequest(DomainModel):
    decision: Literal["approve", "reject"]
    actor: str = Field(default="author", min_length=1, max_length=100)
    note: str = Field(default="", max_length=2000)
    selected_option_id: str | None = None


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


class CharacterProposalRequest(DomainModel):
    name: str = Field(min_length=1, max_length=255)
    role: str = Field(default="", max_length=100)
    brief: str = Field(default="", max_length=5000)
    apply: bool = False


class CharacterProposalResponse(DomainModel):
    proposal: CharacterProfile
    bible: StoryBible | None = None


class WorldbuildingProposalRequest(DomainModel):
    goal: str = Field(min_length=1, max_length=5000)
    apply: bool = False


class WorldbuildingProposalResponse(DomainModel):
    proposal: WorldbuildingProposal
    bible: StoryBible | None = None


class ForeshadowingProposalRequest(DomainModel):
    scene_goal: str = Field(min_length=1, max_length=5000)
    max_actions: int = Field(default=3, ge=1, le=10)
    apply: bool = False


class ForeshadowingProposalResponse(DomainModel):
    proposal: ForeshadowingProposal
    bible: StoryBible | None = None


class BibleEntryRequest(DomainModel):
    value: dict[str, Any] | str
    expected_version: int | None = Field(default=None, ge=1)


class TimelineEventRequest(DomainModel):
    sequence: int = Field(default=0, ge=0)
    label: str = ""
    time_reference: str = ""
    summary: str = Field(min_length=1)
    participants: list[str] = Field(default_factory=list)
    expected_version: int | None = Field(default=None, ge=1)

    def to_event(self, project_id: str) -> TimelineEvent:
        return TimelineEvent(project_id=project_id, **self.model_dump(exclude={"expected_version"}))


class ForeshadowingCreateRequest(DomainModel):
    description: str = Field(min_length=1, max_length=5000)
    planted_at: str | None = None
    expected_payoff: str | None = None
    expected_version: int | None = Field(default=None, ge=1)


class ForeshadowingResolveRequest(DomainModel):
    resolution: str = Field(min_length=1, max_length=5000)
    expected_version: int | None = Field(default=None, ge=1)


class PlotSelectionRequest(DomainModel):
    option_id: str = Field(min_length=1)


class DraftRevisionRequest(DomainModel):
    instruction: str = Field(min_length=1, max_length=10_000)


class ManualDraftRevisionRequest(DomainModel):
    body: str = Field(min_length=1, max_length=2_000_000)
    note: str = Field(default="作者手工编辑", max_length=2000)
    run_checks: bool = False


class DraftRejectRequest(DomainModel):
    reason: str = Field(min_length=1, max_length=5000)


class DraftDiffResponse(DomainModel):
    from_draft_id: str
    to_draft_id: str
    unified_diff: str


class QualityIssue(DomainModel):
    id: str
    project_id: str
    issue_type: Literal["continuity", "fact", "memory"]
    status: Literal["open", "resolved", "ignored"] = "open"
    severity: Literal["info", "warning", "error"] = "warning"
    raw_level: str = ""
    category: str = ""
    title: str
    description: str
    evidence: str = ""
    suggestion: str = ""
    draft_id: str | None = None
    chapter_id: str | None = None
    chapter_title: str | None = None
    run_id: str | None = None
    memory_ids: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    resolution_note: str = ""
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None


class QualityIssueSummary(DomainModel):
    total: int = Field(ge=0)
    open: int = Field(ge=0)
    resolved: int = Field(ge=0)
    ignored: int = Field(ge=0)
    error: int = Field(ge=0)
    warning: int = Field(ge=0)
    info: int = Field(ge=0)


class QualityIssueListResponse(DomainModel):
    issues: list[QualityIssue]
    summary: QualityIssueSummary


class QualityIssueUpdateRequest(DomainModel):
    status: Literal["open", "resolved", "ignored"] | None = None
    resolution_note: str | None = Field(default=None, max_length=2000)


class QualityIssueRevisionRequest(DomainModel):
    instruction: str | None = Field(default=None, max_length=10_000)


class StoryBibleVersionSummary(DomainModel):
    bible_id: str
    project_id: str
    version: int = Field(ge=1)
    created_at: datetime
    is_current: bool = False


class BibleDiffResponse(DomainModel):
    from_version: int = Field(ge=1)
    to_version: int = Field(ge=1)
    unified_diff: str
