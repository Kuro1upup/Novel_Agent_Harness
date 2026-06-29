"""Ordered manuscript structure for volumes and chapters."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import ProjectResource


class ManuscriptVolume(ProjectResource):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    position: int = Field(default=1, ge=1)
    status: Literal["active", "archived"] = "active"


class ManuscriptChapter(ProjectResource):
    volume_id: str
    title: str = Field(min_length=1, max_length=255)
    summary: str = Field(default="", max_length=5000)
    position: int = Field(default=1, ge=1)
    status: Literal["planned", "drafting", "accepted", "completed"] = "planned"
    draft_id: str | None = None
