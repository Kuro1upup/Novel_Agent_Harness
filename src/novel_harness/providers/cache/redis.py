"""Redis-backed ephemeral JSON cache and notification provider."""

from __future__ import annotations

import json
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

from .base import CacheError, CacheProvider


class RedisCacheProvider(CacheProvider):
    def __init__(
        self,
        *,
        host: str,
        port: int,
        password: str | None,
        database: int = 0,
        socket_timeout: float = 1.0,
        client: Any | None = None,
    ) -> None:
        if not host.strip():
            raise ValueError("Redis host must not be empty")
        if not 1 <= port <= 65535:
            raise ValueError("Redis port is invalid")
        if database < 0:
            raise ValueError("Redis database must not be negative")
        self._client: Any = client or Redis(
            host=host,
            port=port,
            password=password or None,
            db=database,
            decode_responses=True,
            socket_connect_timeout=socket_timeout,
            socket_timeout=socket_timeout,
            health_check_interval=30,
        )

    def get_json(self, key: str) -> Any | None:
        try:
            value = self._client.get(key)
        except RedisError as exc:
            raise CacheError(f"Redis read failed: {type(exc).__name__}") from exc
        if value is None:
            return None
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise CacheError("Redis cached value is not valid JSON") from exc

    def set_json(self, key: str, value: Any, *, ttl_seconds: int) -> bool:
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be positive")
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        try:
            return bool(self._client.set(key, payload, ex=ttl_seconds))
        except RedisError as exc:
            raise CacheError(f"Redis write failed: {type(exc).__name__}") from exc

    def delete(self, *keys: str) -> int:
        if not keys:
            return 0
        try:
            return int(self._client.delete(*keys))
        except RedisError as exc:
            raise CacheError(f"Redis delete failed: {type(exc).__name__}") from exc

    def publish(self, channel: str, value: Any) -> int:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        try:
            return int(self._client.publish(channel, payload))
        except RedisError as exc:
            raise CacheError(f"Redis publish failed: {type(exc).__name__}") from exc

    def health(self) -> bool:
        try:
            return bool(self._client.ping())
        except RedisError:
            return False


class FailOpenCacheProvider(CacheProvider):
    """Suppress cache outages while preserving authoritative service behavior."""

    def __init__(self, primary: CacheProvider) -> None:
        self.primary = primary

    def get_json(self, key: str) -> Any | None:
        try:
            return self.primary.get_json(key)
        except (CacheError, OSError):
            return None

    def set_json(self, key: str, value: Any, *, ttl_seconds: int) -> bool:
        try:
            return self.primary.set_json(key, value, ttl_seconds=ttl_seconds)
        except (CacheError, OSError):
            return False

    def delete(self, *keys: str) -> int:
        try:
            return self.primary.delete(*keys)
        except (CacheError, OSError):
            return 0

    def publish(self, channel: str, value: Any) -> int:
        try:
            return self.primary.publish(channel, value)
        except (CacheError, OSError):
            return 0

    def health(self) -> bool:
        try:
            return self.primary.health()
        except (CacheError, OSError):
            return False
