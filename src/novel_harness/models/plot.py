"""Plot planning models."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .base import ProjectResource


class PlotOption(ProjectResource):
    plot_plan_id: str | None = None
    title: str
    summary: str
    conflict: str = ""
    payoff: str = ""
    risks: list[str] = Field(default_factory=list)
    foreshadowing: list[str] = Field(default_factory=list)
    canon_risks: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlotPlan(ProjectResource):
    current_arc: str = ""
    arc_goal: str = ""
    conflict: str = ""
    stakes: str = ""
    turning_points: list[str] = Field(default_factory=list)
    climax_options: list[str] = Field(default_factory=list)
    foreshadowing_to_plant: list[str] = Field(default_factory=list)
    foreshadowing_to_payoff: list[str] = Field(default_factory=list)
    next_chapter_options: list[PlotOption | dict[str, Any]] = Field(default_factory=list)
    bible_version: int = Field(default=1, ge=1)
