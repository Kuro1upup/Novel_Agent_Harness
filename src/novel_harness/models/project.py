"""Novel project models."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .base import DomainModel, new_id, utc_now


class NovelProject(DomainModel):
    id: str = Field(default_factory=new_id)
    owner_user_id: int = Field(default=0, ge=0)
    name: str = Field(min_length=1, max_length=255)
    genre: str = Field(min_length=1, max_length=100)
    sub_genre: str | None = Field(default=None, max_length=100)
    premise: str = ""
    target_audience: str = ""
    tone: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
