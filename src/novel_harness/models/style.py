"""Writing-style analysis models."""

from __future__ import annotations

from pydantic import Field

from .base import ProjectResource


class StyleProfile(ProjectResource):
    narrative_pov: str = ""
    tense: str = ""
    sentence_length: float = Field(default=0, ge=0)
    paragraph_length: float = Field(default=0, ge=0)
    dialogue_ratio: float = Field(default=0, ge=0, le=1)
    common_phrases: list[str] = Field(default_factory=list)
    rhetorical_devices: list[str] = Field(default_factory=list)
    pacing: str = ""
    emotional_temperature: str = ""
    taboo_patterns: list[str] = Field(default_factory=list)
    style_summary: str = ""
    continuation_guidelines: list[str] = Field(default_factory=list)
    source_document_ids: list[str] = Field(default_factory=list)
    version: int = Field(default=1, ge=1)
