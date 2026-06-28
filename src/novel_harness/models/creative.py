"""Non-canonical creative proposals returned by authoring agents."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class WorldbuildingProposal(BaseModel):
    world_summary: str
    rules: list[dict[str, Any] | str] = Field(default_factory=list)
    factions: list[dict[str, Any]] = Field(default_factory=list)
    locations: list[dict[str, Any]] = Field(default_factory=list)
    canon_conflicts: list[str] = Field(default_factory=list)
    research_gaps: list[str] = Field(default_factory=list)


class ForeshadowingAction(BaseModel):
    action: Literal["plant", "reinforce", "payoff"]
    description: str
    subtle_expression: str
    target_payoff: str
    canon_risks: list[str] = Field(default_factory=list)


class ForeshadowingProposal(BaseModel):
    actions: list[ForeshadowingAction] = Field(default_factory=list)
    deferred_items: list[str] = Field(default_factory=list)
