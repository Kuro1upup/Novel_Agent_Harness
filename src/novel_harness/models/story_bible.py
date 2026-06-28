"""Versioned story canon models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .base import ProjectResource
from .character import CharacterProfile


class TimelineEvent(ProjectResource):
    sequence: int = Field(default=0, ge=0)
    label: str = ""
    time_reference: str = ""
    summary: str
    participants: list[str] = Field(default_factory=list)


class ForeshadowingItem(ProjectResource):
    description: str
    planted_at: str | None = None
    expected_payoff: str | None = None
    status: Literal["planned", "planted", "resolved", "abandoned"] = "planned"


class StoryBible(ProjectResource):
    world_summary: str = ""
    rules: list[dict[str, Any] | str] = Field(default_factory=list)
    factions: list[dict[str, Any]] = Field(default_factory=list)
    characters: list[CharacterProfile] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    locations: list[dict[str, Any]] = Field(default_factory=list)
    unresolved_threads: list[dict[str, Any] | str] = Field(default_factory=list)
    foreshadowing_items: list[ForeshadowingItem] = Field(default_factory=list)
    resolved_threads: list[dict[str, Any] | str] = Field(default_factory=list)
    canon_events: list[dict[str, Any] | str] = Field(default_factory=list)
    version: int = Field(default=1, ge=1)


class CanonPatch(ProjectResource):
    """A proposed, auditable patch which is not canon until accepted."""

    draft_id: str
    base_bible_version: int = Field(ge=1)
    operations: list[dict[str, Any]] = Field(default_factory=list)
    status: Literal["pending", "accepted", "rejected"] = "pending"
    accepted_bible_version: int | None = None
