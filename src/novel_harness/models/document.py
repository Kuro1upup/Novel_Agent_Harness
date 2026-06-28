"""Document metadata models."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import ProjectResource


class Document(ProjectResource):
    filename: str
    mime_type: str
    size_bytes: int = Field(ge=0)
    content_hash: str
    object_key: str
    parsed_object_key: str | None = None
    status: Literal["pending", "ready", "failed", "cleanup_required"] = "pending"
    error_message: str | None = None


class DocumentChunk(ProjectResource):
    document_id: str
    ordinal: int = Field(ge=0)
    content_hash: str
    object_key: str | None = None
    preview: str = ""
    vector_id: str | None = None
    status: Literal["pending", "ready", "failed", "cleanup_required"] = "pending"
