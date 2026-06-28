from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from novel_harness.core.context_manager import ContextManager
from novel_harness.providers.vectorstore import VectorMatch


class StubEmbedding:
    dimension = 2

    def embed_query(self, text: str) -> list[float]:
        assert text
        return [0.5, 0.5]


class StubVectorStore:
    def __init__(self, matches: list[VectorMatch]) -> None:
        self.matches = matches
        self.calls: list[dict[str, Any]] = []

    def search(
        self,
        *,
        project_id: str,
        vector: list[float],
        limit: int,
        source_types: tuple[str, ...] | None,
    ) -> list[VectorMatch]:
        self.calls.append(
            {
                "project_id": project_id,
                "vector": vector,
                "limit": limit,
                "source_types": source_types,
            }
        )
        # Intentionally return every match to verify ContextManager's own isolation.
        return self.matches


class StubObjectStore:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects

    def get_bytes(self, key: str) -> bytes:
        return self.objects[key]


@dataclass
class StubDocument:
    id: str
    project_id: str
    parsed_object_key: str | None


class StubDocumentRepository:
    def __init__(self, documents: dict[str, StubDocument]) -> None:
        self.documents = documents

    def get(self, document_id: str) -> StubDocument | None:
        return self.documents.get(document_id)


class StubRepositories:
    def __init__(self, documents: dict[str, StubDocument]) -> None:
        self.documents = StubDocumentRepository(documents)


def match(
    *,
    record_id: str,
    project_id: str = "project-a",
    source_id: str | None = None,
    source_type: str = "research",
    ordinal: int = 0,
    score: float = 0.5,
    content_hash: str | None = None,
    preview: str = "preview",
    verification_status: str = "fetched",
    credibility_score: float = 0.8,
    source_url: str = "https://example.com/source",
) -> VectorMatch:
    metadata: dict[str, object] = {"preview": preview}
    if source_type == "research":
        metadata.update(
            {
                "verification_status": verification_status,
                "credibility_score": credibility_score,
                "source_url": source_url,
            }
        )
    return VectorMatch(
        id=record_id,
        project_id=project_id,
        source_id=source_id or record_id,
        source_type=source_type,
        chunk_ordinal=ordinal,
        content_hash=content_hash or record_id,
        score=score,
        metadata=metadata,
    )


def test_assemble_preserves_existing_priority_api() -> None:
    manager = ContextManager(max_characters=100)

    value = manager.assemble({"research": "soft", "story_bible": "hard"})

    assert value.index("## story_bible") < value.index("## research")


def test_retrieve_enforces_project_and_source_type_and_priority() -> None:
    store = StubVectorStore(
        [
            match(record_id="research", score=0.99),
            match(record_id="canon", source_type="story_bible", score=0.1, preview="canon"),
            match(record_id="foreign", project_id="project-b", preview="secret"),
            match(record_id="style", source_type="style", preview="filtered"),
        ]
    )
    manager = ContextManager(
        vector_store=store,  # type: ignore[arg-type]
        embedding_provider=StubEmbedding(),  # type: ignore[arg-type]
    )

    context = manager.retrieve(
        "project-a",
        "query",
        source_types=["story_bible", "research"],
        limit=4,
    )

    assert [fragment.source_id for fragment in context.fragments] == ["canon", "research"]
    assert all(fragment.content != "secret" for fragment in context.fragments)
    assert store.calls == [
        {
            "project_id": "project-a",
            "vector": [0.5, 0.5],
            "limit": 4,
            "source_types": ("story_bible", "research"),
        }
    ]


def test_retrieve_resolves_document_from_project_owned_object() -> None:
    text = ("before-" * 40) + "unique preview" + ("-authoritative" * 100)
    store = StubVectorStore(
        [
            match(
                record_id="doc-vector",
                source_id="doc-a",
                source_type="document",
                preview="unique preview",
            )
        ]
    )
    repositories = StubRepositories(
        {"doc-a": StubDocument("doc-a", "project-a", "parsed/doc-a.txt")}
    )
    manager = ContextManager(
        max_characters=2_000,
        vector_store=store,  # type: ignore[arg-type]
        embedding_provider=StubEmbedding(),  # type: ignore[arg-type]
        object_store=StubObjectStore({"parsed/doc-a.txt": text.encode()}),  # type: ignore[arg-type]
        repositories=repositories,  # type: ignore[arg-type]
    )

    context = manager.retrieve("project-a", "needle")

    assert len(context.fragments) == 1
    assert context.fragments[0].content.startswith("unique preview")
    assert "-authoritative" in context.fragments[0].content
    assert len(context.fragments[0].content) > len("unique preview")


def test_retrieve_rejects_document_owned_by_another_project() -> None:
    store = StubVectorStore(
        [
            match(
                record_id="poisoned",
                source_id="foreign-doc",
                source_type="document",
                preview="foreign secret",
            )
        ]
    )
    repositories = StubRepositories(
        {"foreign-doc": StubDocument("foreign-doc", "project-b", "foreign.txt")}
    )
    manager = ContextManager(
        vector_store=store,  # type: ignore[arg-type]
        embedding_provider=StubEmbedding(),  # type: ignore[arg-type]
        object_store=StubObjectStore({"foreign.txt": b"foreign secret"}),  # type: ignore[arg-type]
        repositories=repositories,  # type: ignore[arg-type]
    )

    context = manager.retrieve("project-a", "query")

    assert context.fragments == ()


def test_retrieve_deduplicates_and_honors_character_budget() -> None:
    store = StubVectorStore(
        [
            match(record_id="first", content_hash="same", preview="12345678"),
            match(record_id="duplicate", content_hash="same", preview="duplicate"),
            match(record_id="second", preview="abcdef"),
        ]
    )
    manager = ContextManager(
        max_characters=10,
        vector_store=store,  # type: ignore[arg-type]
        embedding_provider=StubEmbedding(),  # type: ignore[arg-type]
    )

    context = manager.retrieve("project-a", "query")

    assert [fragment.source_id for fragment in context.fragments] == ["first", "second"]
    assert [fragment.content for fragment in context.fragments] == ["12345678", "ab"]
    assert context.total_characters == 10
    assert context.truncated is True
    assert context.fragments[-1].truncated is True


def test_retrieve_rejects_unverified_low_credibility_and_challenge_research() -> None:
    store = StubVectorStore(
        [
            match(
                record_id="unverified",
                verification_status="snippet_only",
                preview="search snippet",
            ),
            match(
                record_id="weak",
                credibility_score=0.2,
                preview="weak source",
            ),
            match(
                record_id="challenge",
                source_url="https://wappass.baidu.com/static/captcha/",
                preview="security challenge",
            ),
            match(record_id="trusted", preview="trusted evidence"),
        ]
    )
    manager = ContextManager(
        vector_store=store,  # type: ignore[arg-type]
        embedding_provider=StubEmbedding(),  # type: ignore[arg-type]
    )

    context = manager.retrieve("project-a", "query")

    assert [fragment.source_id for fragment in context.fragments] == ["trusted"]


@pytest.mark.parametrize(
    ("project_id", "query", "limit"),
    [("", "query", 1), ("project-a", "", 1), ("project-a", "query", 0)],
)
def test_retrieve_validates_inputs(project_id: str, query: str, limit: int) -> None:
    manager = ContextManager(
        vector_store=StubVectorStore([]),  # type: ignore[arg-type]
        embedding_provider=StubEmbedding(),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError):
        manager.retrieve(project_id, query, limit=limit)
