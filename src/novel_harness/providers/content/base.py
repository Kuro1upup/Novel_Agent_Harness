"""Provider-neutral contracts for fetching readable web content."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from novel_harness.exceptions import ProviderError


class ContentFetchError(ProviderError):
    """Base error raised by content fetchers."""


class ContentFetchConfigurationError(ContentFetchError):
    """The content fetcher is configured incorrectly."""


class ContentFetchSecurityError(ContentFetchError):
    """A URL is unsafe to fetch."""


class ContentFetchTransportError(ContentFetchError):
    """A remote server could not provide content."""


class UnsupportedContentTypeError(ContentFetchError):
    """A response is not HTML or plain text."""


class ContentTooLargeError(ContentFetchError):
    """A response exceeds the configured byte limit."""


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Normalized readable content returned by a fetcher."""

    requested_url: str
    final_url: str
    content: str
    content_type: str
    status_code: int
    title: str = ""
    byte_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def url(self) -> str:
        """Return the final URL as a convenient compatibility alias."""

        return self.final_url

    @property
    def text(self) -> str:
        """Return extracted content as a convenient compatibility alias."""

        return self.content


class ContentFetcher(ABC):
    """Synchronous interface for retrieving readable web content."""

    @abstractmethod
    def fetch(self, url: str) -> FetchResult:
        """Fetch and normalize one public HTTP(S) resource."""
