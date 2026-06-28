"""Ephemeral cache and notification provider contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from novel_harness.exceptions import ProviderError


class CacheError(ProviderError):
    """Base cache provider error."""


class CacheProvider(ABC):
    @abstractmethod
    def get_json(self, key: str) -> Any | None:
        """Return a JSON-compatible value or ``None``."""

    @abstractmethod
    def set_json(self, key: str, value: Any, *, ttl_seconds: int) -> bool:
        """Store a JSON-compatible value."""

    @abstractmethod
    def delete(self, *keys: str) -> int:
        """Delete exact keys."""

    @abstractmethod
    def publish(self, channel: str, value: Any) -> int:
        """Publish a best-effort JSON notification."""

    @abstractmethod
    def health(self) -> bool:
        """Return whether the cache service is reachable."""
