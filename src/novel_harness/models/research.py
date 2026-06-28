"""Research and search-result models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, HttpUrl

from .base import DomainModel, ProjectResource, utc_now


class SearchResult(ProjectResource):
    query: str
    title: str
    url: HttpUrl | str
    snippet: str = ""
    engine: str | None = None
    published_at: datetime | None = None
    score: float | None = None


class EvidenceSnippet(DomainModel):
    """A short, attributable passage extracted from fetched source content."""

    text: str = Field(min_length=1, max_length=2000)
    source_url: HttpUrl | str
    locator: str = ""
    content_hash: str
    retrieved_at: datetime = Field(default_factory=utc_now)


class ResearchNote(ProjectResource):
    topic: str
    query: str
    source_title: str
    source_url: HttpUrl | str
    source_type: str = "web"
    credibility_score: float = Field(default=0.5, ge=0, le=1)
    extracted_facts: list[str] = Field(default_factory=list)
    writing_implications: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    uncertainty: str | None = None
    needs_further_research: list[str] = Field(default_factory=list)
    evidence_snippets: list[EvidenceSnippet] = Field(default_factory=list)
    verification_status: Literal[
        "mock", "snippet_only", "fetched", "corroborated", "fetch_failed"
    ] = "snippet_only"
    corroborating_urls: list[HttpUrl | str] = Field(default_factory=list)
    source_content_hash: str | None = None
    source_object_key: str | None = None
    source_retrieved_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
