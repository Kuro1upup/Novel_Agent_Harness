"""Deterministic search provider for tests and offline development."""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence

from .base import SearchProvider, SearchQuery, SearchResult

MockSearchResponder = Callable[[SearchQuery], Sequence[SearchResult]]


class MockSearchProvider(SearchProvider):
    """Return configured results by exact query, or deterministic mock data."""

    def __init__(
        self,
        results: Mapping[str, Sequence[SearchResult]] | None = None,
        *,
        responder: MockSearchResponder | None = None,
    ) -> None:
        self._results = {key: tuple(copy.deepcopy(value)) for key, value in (results or {}).items()}
        self._responder = responder
        self.calls: list[SearchQuery] = []

    def search(
        self,
        query: str | SearchQuery,
        *,
        max_results: int | None = None,
    ) -> list[SearchResult]:
        normalized = self.normalize_query(query, max_results)
        self.calls.append(normalized)
        if self._responder:
            results = list(self._responder(normalized))
        elif normalized.text in self._results:
            results = list(copy.deepcopy(self._results[normalized.text]))
        else:
            results = [
                SearchResult(
                    title=f"Mock result for: {normalized.text}",
                    url="mock://search/result-1",
                    snippet=(
                        "Offline mock search result; do not treat this content as "
                        "a verified external fact."
                    ),
                    source="mock",
                    score=0.0,
                    metadata={"mock": True, "verified": False},
                )
            ]
        return results[: normalized.max_results]
