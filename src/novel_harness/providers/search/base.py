"""Provider-neutral synchronous search contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from novel_harness.exceptions import ProviderError


class SearchError(ProviderError):
    """Base error raised by search providers."""


class SearchConfigurationError(SearchError):
    """Search provider configuration is invalid."""


class SearchTransportError(SearchError):
    """A remote search service failed."""


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """Portable search request."""

    text: str
    max_results: int = 10
    categories: tuple[str, ...] = ()
    language: str = "auto"
    time_range: str | None = None
    safesearch: int = 1
    page: int = 1

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise SearchConfigurationError("Search query must not be empty")
        if not 1 <= self.max_results <= 100:
            raise SearchConfigurationError("max_results must be between 1 and 100")
        if self.page < 1:
            raise SearchConfigurationError("page must be at least 1")
        if self.safesearch not in {0, 1, 2}:
            raise SearchConfigurationError("safesearch must be 0, 1, or 2")


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Normalized search result."""

    title: str
    url: str
    snippet: str = ""
    source: str = ""
    score: float | None = None
    published_at: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @property
    def content(self) -> str:
        return self.snippet

    @property
    def engine(self) -> str:
        return self.source

    @property
    def source_type(self) -> str:
        return self.source or "web"


class SearchProvider(ABC):
    """Synchronous web-search interface."""

    @abstractmethod
    def search(
        self,
        query: str | SearchQuery,
        *,
        max_results: int | None = None,
    ) -> list[SearchResult]:
        """Search for ``query`` and return normalized, ordered results."""

    @staticmethod
    def normalize_query(query: str | SearchQuery, max_results: int | None = None) -> SearchQuery:
        if isinstance(query, str):
            return SearchQuery(
                text=query,
                max_results=max_results if max_results is not None else 10,
            )
        if max_results is None or max_results == query.max_results:
            return query
        return SearchQuery(
            text=query.text,
            max_results=max_results,
            categories=query.categories,
            language=query.language,
            time_range=query.time_range,
            safesearch=query.safesearch,
            page=query.page,
        )
