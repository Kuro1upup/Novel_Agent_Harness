"""Shared Pydantic model primitives."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


def new_id() -> str:
    """Return a sortable-independent public identifier."""

    return str(uuid4())


class DomainModel(BaseModel):
    """Base class for public domain models."""

    model_config = ConfigDict(
        extra="forbid",
        from_attributes=True,
        validate_assignment=True,
    )


class ProjectResource(DomainModel):
    """A domain resource owned by one novel project."""

    id: str = Field(default_factory=new_id)
    project_id: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
