"""Character models."""

from __future__ import annotations

from pydantic import Field

from .base import ProjectResource


class CharacterProfile(ProjectResource):
    name: str = Field(min_length=1, max_length=255)
    role: str = ""
    age: int | str | None = None
    background: str = ""
    motivation: str = ""
    desire: str = ""
    fear: str = ""
    secret: str = ""
    relationship_map: dict[str, str] = Field(default_factory=dict)
    speech_style: str = ""
    arc_stage: str = ""
    constraints: list[str] = Field(default_factory=list)
