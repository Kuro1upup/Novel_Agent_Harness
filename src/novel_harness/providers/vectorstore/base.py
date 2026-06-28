"""Provider-neutral vector-store contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from novel_harness.exceptions import ProviderError


class VectorStoreError(ProviderError):
    """Base vector-store error."""


class VectorStoreConfigurationError(VectorStoreError):
    """Vector-store configuration or input is invalid."""


class VectorStoreTransportError(VectorStoreError):
    """The backing vector database failed."""


@dataclass(frozen=True, slots=True)
class VectorRecord:
    """One vector and its retrieval metadata."""

    id: str
    project_id: str
    source_id: str
    source_type: str
    chunk_ordinal: int
    content_hash: str
    embedding: Sequence[float]
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VectorMatch:
    """Normalized nearest-neighbor result."""

    id: str
    project_id: str
    source_id: str
    source_type: str
    chunk_ordinal: int
    content_hash: str
    score: float
    metadata: Mapping[str, Any] = field(default_factory=dict)


class VectorStore(ABC):
    """Synchronous project-isolated vector-store interface."""

    @abstractmethod
    def ensure_collection(self) -> None:
        """Create the collection and index when absent."""

    @abstractmethod
    def upsert(self, records: Sequence[VectorRecord]) -> int:
        """Insert or replace records and return the number accepted."""

    @abstractmethod
    def search(
        self,
        *,
        project_id: str,
        vector: Sequence[float],
        limit: int = 10,
        source_types: Sequence[str] | None = None,
    ) -> list[VectorMatch]:
        """Find nearest neighbors scoped to exactly one project."""

    @abstractmethod
    def delete(
        self,
        *,
        project_id: str,
        ids: Sequence[str] | None = None,
        source_id: str | None = None,
    ) -> int:
        """Delete selected project vectors and return a best-effort count."""

    @abstractmethod
    def health(self) -> bool:
        """Return whether the backing service is reachable."""
