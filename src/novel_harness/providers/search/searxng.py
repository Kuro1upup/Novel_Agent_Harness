"""SearXNG JSON Search API provider."""

from __future__ import annotations

import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import httpx

from .base import (
    SearchConfigurationError,
    SearchProvider,
    SearchQuery,
    SearchResult,
    SearchTransportError,
)


class SearXNGSearchProvider(SearchProvider):
    """Call a SearXNG instance using ``GET /search?format=json``."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout: float = 20.0,
        max_retries: int = 2,
        client: httpx.Client | None = None,
        user_agent: str = "novel-agent-harness/0.1",
    ) -> None:
        if not base_url.strip():
            raise SearchConfigurationError("SearXNG base_url must not be empty")
        if timeout <= 0:
            raise SearchConfigurationError("SearXNG timeout must be positive")
        if max_retries < 0:
            raise SearchConfigurationError("SearXNG max_retries cannot be negative")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = client
        self.user_agent = user_agent

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/search"

    def search(
        self,
        query: str | SearchQuery,
        *,
        max_results: int | None = None,
    ) -> list[SearchResult]:
        request = self.normalize_query(query, max_results)
        params: dict[str, str | int] = {
            "q": request.text,
            "format": "json",
            "language": request.language,
            "safesearch": request.safesearch,
            "pageno": request.page,
        }
        if request.categories:
            params["categories"] = ",".join(request.categories)
        if request.time_range:
            params["time_range"] = request.time_range
        data = self._get_with_retry(params)
        raw_results = data.get("results")
        if not isinstance(raw_results, list):
            raise SearchTransportError("SearXNG response is missing a results list")
        results: list[SearchResult] = []
        seen_urls: set[str] = set()
        for raw in raw_results:
            if not isinstance(raw, Mapping):
                continue
            result = self._normalize_result(raw)
            if result is None or result.url in seen_urls:
                continue
            seen_urls.add(result.url)
            results.append(result)
            if len(results) >= request.max_results:
                break
        return results

    def _get_with_retry(self, params: Mapping[str, str | int]) -> Mapping[str, Any]:
        client = self._client or httpx.Client()
        owns_client = self._client is None
        try:
            for attempt in range(self.max_retries + 1):
                try:
                    response = client.get(
                        self.endpoint,
                        params=params,
                        headers={
                            "Accept": "application/json",
                            "User-Agent": self.user_agent,
                        },
                        timeout=self.timeout,
                    )
                    if response.status_code in {408, 429} or response.status_code >= 500:
                        if attempt < self.max_retries:
                            time.sleep(min(0.25 * (2**attempt), 2.0))
                            continue
                    response.raise_for_status()
                    data = response.json()
                    if not isinstance(data, Mapping):
                        raise SearchTransportError("SearXNG response root must be a JSON object")
                    return data
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt >= self.max_retries:
                        raise SearchTransportError(
                            f"SearXNG request failed after {attempt + 1} attempts: {exc}"
                        ) from exc
                    time.sleep(min(0.25 * (2**attempt), 2.0))
                except httpx.HTTPStatusError as exc:
                    body = exc.response.text[:500]
                    raise SearchTransportError(
                        f"SearXNG returned HTTP {exc.response.status_code}: {body}"
                    ) from exc
                except ValueError as exc:
                    raise SearchTransportError("SearXNG returned invalid JSON") from exc
        finally:
            if owns_client:
                client.close()
        raise SearchTransportError("SearXNG request failed without a response")

    @staticmethod
    def _normalize_result(raw: Mapping[str, Any]) -> SearchResult | None:
        url = raw.get("url")
        if not isinstance(url, str) or not url.strip():
            return None
        title = raw.get("title")
        snippet = raw.get("content") or raw.get("snippet") or ""
        engines = raw.get("engines")
        if isinstance(engines, list):
            source = ",".join(str(engine) for engine in engines)
        else:
            source = str(raw.get("engine") or "")
        metadata = {
            key: value
            for key, value in raw.items()
            if key
            not in {
                "url",
                "title",
                "content",
                "snippet",
                "engine",
                "engines",
                "score",
                "publishedDate",
                "published_date",
            }
            and _is_json_value(value)
        }
        return SearchResult(
            title=str(title or url),
            url=url,
            snippet=str(snippet),
            source=source,
            score=_optional_float(raw.get("score")),
            published_at=_parse_datetime(raw.get("publishedDate") or raw.get("published_date")),
            metadata=metadata,
        )


def _optional_float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    candidate = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except ValueError:
        return None


def _is_json_value(value: Any) -> bool:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_json_value(item) for key, item in value.items())
    return False
