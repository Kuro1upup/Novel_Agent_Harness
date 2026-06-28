from __future__ import annotations

from typing import Any

from redis.exceptions import ConnectionError

from novel_harness.providers.cache import (
    FailOpenCacheProvider,
    RedisCacheProvider,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.messages: list[tuple[str, str]] = []

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str, *, ex: int) -> bool:
        assert ex > 0
        self.values[key] = value
        return True

    def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            deleted += key in self.values
            self.values.pop(key, None)
        return deleted

    def publish(self, channel: str, value: str) -> int:
        self.messages.append((channel, value))
        return 1

    def ping(self) -> bool:
        return True


class FailingRedis:
    def __getattr__(self, _name: str) -> Any:
        def fail(*_args: Any, **_kwargs: Any) -> Any:
            raise ConnectionError("offline")

        return fail


def test_redis_cache_round_trips_json_and_publishes() -> None:
    client = FakeRedis()
    cache = RedisCacheProvider(
        host="localhost",
        port=20005,
        password="secret",
        client=client,
    )

    assert cache.set_json("key", {"中文": [1, 2]}, ttl_seconds=60)
    assert cache.get_json("key") == {"中文": [1, 2]}
    assert cache.publish("events", {"status": "ready"}) == 1
    assert cache.delete("key") == 1
    assert cache.get_json("key") is None
    assert cache.health()


def test_fail_open_cache_suppresses_redis_outage() -> None:
    cache = FailOpenCacheProvider(
        RedisCacheProvider(
            host="localhost",
            port=20005,
            password="secret",
            client=FailingRedis(),
        )
    )

    assert cache.get_json("key") is None
    assert cache.set_json("key", {"value": 1}, ttl_seconds=60) is False
    assert cache.publish("events", {"value": 1}) == 0
    assert cache.delete("key") == 0
    assert cache.health() is False
