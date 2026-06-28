"""No-op cache used for tests and fail-open operation."""

from __future__ import annotations

from typing import Any

from .base import CacheProvider


class NullCacheProvider(CacheProvider):
    def get_json(self, key: str) -> Any | None:
        del key
        return None

    def set_json(self, key: str, value: Any, *, ttl_seconds: int) -> bool:
        del key, value, ttl_seconds
        return False

    def delete(self, *keys: str) -> int:
        del keys
        return 0

    def publish(self, channel: str, value: Any) -> int:
        del channel, value
        return 0

    def health(self) -> bool:
        return True
