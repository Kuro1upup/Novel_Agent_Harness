from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from novel_harness.config import Settings
from novel_harness.providers.cache import NullCacheProvider
from novel_harness.providers.embedding import DeterministicEmbeddingProvider
from novel_harness.providers.search import MockSearchProvider
from novel_harness.providers.vectorstore import VectorMatch, VectorRecord
from novel_harness.runtime import Runtime
from novel_harness.storage.orm import Base


class FakeObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def ensure_bucket(self) -> None:
        return None

    def put_bytes(
        self, key: str, data: bytes, *, content_type: str = "application/octet-stream"
    ) -> Any:
        self.objects[key] = data
        return {"key": key, "size": len(data), "content_type": content_type}

    def put_file(
        self,
        key: str,
        path: str | Path,
        *,
        content_type: str = "application/octet-stream",
    ) -> Any:
        return self.put_bytes(key, Path(path).read_bytes(), content_type=content_type)

    def get_bytes(self, key: str) -> bytes:
        return self.objects[key]

    def exists(self, key: str) -> bool:
        return key in self.objects

    def remove(self, key: str) -> None:
        self.objects.pop(key, None)

    def health(self) -> bool:
        return True

    def presigned_get(self, key: str, *, expires: timedelta = timedelta(minutes=15)) -> str:
        return f"http://example.test/{key}?expires={int(expires.total_seconds())}"


class FakeVectorStore:
    def __init__(self) -> None:
        self.records: dict[str, VectorRecord] = {}

    def ensure_collection(self) -> None:
        return None

    def upsert(self, records: Sequence[VectorRecord]) -> int:
        self.records.update({record.id: record for record in records})
        return len(records)

    def search(
        self,
        *,
        project_id: str,
        vector: Sequence[float],
        limit: int = 10,
        source_types: Sequence[str] | None = None,
    ) -> list[VectorMatch]:
        del vector
        matches = [
            VectorMatch(
                id=record.id,
                project_id=record.project_id,
                source_id=record.source_id,
                source_type=record.source_type,
                chunk_ordinal=record.chunk_ordinal,
                content_hash=record.content_hash,
                score=1.0,
                metadata=record.metadata,
            )
            for record in self.records.values()
            if record.project_id == project_id
            and (not source_types or record.source_type in source_types)
        ]
        return matches[:limit]

    def delete(
        self,
        *,
        project_id: str,
        ids: Sequence[str] | None = None,
        source_id: str | None = None,
    ) -> int:
        selected = [
            key
            for key, record in self.records.items()
            if record.project_id == project_id
            and (ids is None or key in ids)
            and (source_id is None or record.source_id == source_id)
        ]
        for key in selected:
            del self.records[key]
        return len(selected)

    def health(self) -> bool:
        return True


@pytest.fixture
def engine() -> Iterator[Any]:
    value = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(value, "connect")
    def enable_foreign_keys(dbapi_connection: Any, _: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(value)
    yield value
    Base.metadata.drop_all(value)
    value.dispose()


@pytest.fixture
def session(engine: Any) -> Iterator[Session]:
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    value = factory()
    yield value
    value.rollback()
    value.close()


@pytest.fixture
def fake_object_store() -> FakeObjectStore:
    return FakeObjectStore()


@pytest.fixture
def fake_vector_store() -> FakeVectorStore:
    return FakeVectorStore()


@pytest.fixture
def runtime(
    engine: Any,
    fake_object_store: FakeObjectStore,
    fake_vector_store: FakeVectorStore,
) -> Runtime:
    settings = Settings(
        llm_provider="mock",
        search_provider="mock",
        originality_max_contiguous_chars=100,
    )
    return Runtime(
        settings,
        engine=engine,
        session_factory=sessionmaker(bind=engine, expire_on_commit=False),
        search_provider=MockSearchProvider(),
        object_store=fake_object_store,
        vector_store=fake_vector_store,
        embedding_provider=DeterministicEmbeddingProvider(384),
        cache_provider=NullCacheProvider(),
    )
