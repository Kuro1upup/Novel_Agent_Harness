from __future__ import annotations

import hashlib
from typing import Any

import pytest

from novel_harness.agents import MemoryExtractor
from novel_harness.models import GenerationResult, MemoryRecord, StoryBible
from novel_harness.providers.embedding import DeterministicEmbeddingProvider
from novel_harness.providers.llm import MockLLMProvider
from novel_harness.services import MemoryService, ProjectService, StoryBibleService
from novel_harness.storage.repositories import Repositories


class MemoryCache:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    def get_json(self, key: str) -> Any | None:
        return self.values.get(key)

    def set_json(self, key: str, value: Any, *, ttl_seconds: int) -> bool:
        assert ttl_seconds > 0
        self.values[key] = value
        return True

    def delete(self, *keys: str) -> int:
        for key in keys:
            self.values.pop(key, None)
        return len(keys)

    def publish(self, channel: str, value: Any) -> int:
        del channel, value
        return 0

    def health(self) -> bool:
        return True


def make_accepted_draft(session, fake_object_store):
    project = ProjectService(session).create(name="长安", genre="历史")
    StoryBibleService(session).get(project.id)
    object_key = f"projects/{project.id}/drafts/accepted/chapter.md"
    body = "林川通过城门查验，进入长安。他发现通关文牒上的印记存在异常。"
    fake_object_store.put_bytes(object_key, body.encode("utf-8"))
    draft = GenerationResult(
        project_id=project.id,
        body="",
        object_key=object_key,
        status="accepted",
        bible_version=1,
    )
    Repositories(session).generations.add(draft)
    return project, draft


@pytest.mark.asyncio
async def test_memory_extractor_normalizes_structured_llm_output() -> None:
    provider = MockLLMProvider(
        responses=[
            {
                "summary": "林川进入长安并发现文牒异常。",
                "memories": [
                    {
                        "kind": "location_state",
                        "subject": "林川",
                        "predicate": "location",
                        "value": "长安",
                        "statement": "林川已进入长安。",
                        "confidence": 0.9,
                    }
                ],
            }
        ]
    )
    result = await MemoryExtractor(provider).run(
        "林川进入长安。",
        StoryBible(project_id="project-a"),
        draft_id="draft-a",
    )

    assert result.memories[0].kind == "chapter_summary"
    assert any(memory.kind == "location_state" for memory in result.memories)


@pytest.mark.asyncio
async def test_memory_service_extracts_indexes_and_is_idempotent(
    session,
    fake_object_store,
    fake_vector_store,
) -> None:
    project, draft = make_accepted_draft(session, fake_object_store)
    service = MemoryService(
        session,
        object_store=fake_object_store,
        vector_store=fake_vector_store,
        embedding_provider=DeterministicEmbeddingProvider(),
        extractor=MemoryExtractor(),
        cache_provider=MemoryCache(),
    )

    first = await service.extract_accepted_draft(project.id, draft.id)
    revision = service.state(project.id).revision
    second = await service.extract_accepted_draft(project.id, draft.id)

    assert len(first) == 1
    assert second[0].id == first[0].id
    assert service.state(project.id).revision == revision == 1
    assert fake_vector_store.records[f"memory:{first[0].id}"].source_type == "memory"
    assert service.search(project.id, "通关文牒异常")[0].memory.id == first[0].id


@pytest.mark.asyncio
async def test_rejected_or_draft_content_cannot_update_memory(
    session,
    fake_object_store,
    fake_vector_store,
) -> None:
    project, accepted = make_accepted_draft(session, fake_object_store)
    repositories = Repositories(session)
    repositories.generations.update(accepted.model_copy(update={"status": "rejected"}))
    service = MemoryService(
        session,
        object_store=fake_object_store,
        vector_store=fake_vector_store,
        embedding_provider=DeterministicEmbeddingProvider(),
        extractor=MemoryExtractor(),
        cache_provider=MemoryCache(),
    )

    with pytest.raises(ValueError, match="accepted"):
        await service.extract_accepted_draft(project.id, accepted.id)

    assert repositories.memories.list_active(project.id) == []
    assert fake_vector_store.records == {}


@pytest.mark.asyncio
async def test_memory_rebuild_is_idempotent(
    session,
    fake_object_store,
    fake_vector_store,
) -> None:
    project, _draft = make_accepted_draft(session, fake_object_store)
    service = MemoryService(
        session,
        object_store=fake_object_store,
        vector_store=fake_vector_store,
        embedding_provider=DeterministicEmbeddingProvider(),
        extractor=MemoryExtractor(),
        cache_provider=MemoryCache(),
    )

    first = await service.rebuild(project.id)
    first_statements = {
        memory.statement for memory in Repositories(session).memories.list_active(project.id)
    }
    second = await service.rebuild(project.id)
    second_statements = {
        memory.statement for memory in Repositories(session).memories.list_active(project.id)
    }

    assert first["created_memories"] == second["created_memories"] == 1
    assert first_statements == second_statements
    assert (
        len(
            [
                record
                for record in fake_vector_store.records.values()
                if record.source_type == "memory"
            ]
        )
        == 1
    )


def test_memory_preflight_detects_location_conflict(
    session,
    fake_object_store,
    fake_vector_store,
) -> None:
    project, draft = make_accepted_draft(session, fake_object_store)
    service = MemoryService(
        session,
        object_store=fake_object_store,
        vector_store=fake_vector_store,
        embedding_provider=DeterministicEmbeddingProvider(),
        extractor=MemoryExtractor(),
        cache_provider=MemoryCache(),
    )
    memory = MemoryRecord(
        project_id=project.id,
        kind="location_state",
        subject="林川",
        predicate="location",
        value="长安",
        statement="林川目前位于长安。",
        source_draft_id=draft.id,
        canon_version=1,
        confidence=0.9,
        source_hash=hashlib.sha256(b"location").hexdigest(),
    )
    Repositories(session).memories.add(memory)

    conflicts = service.preflight(project.id, "下一章开场时，林川目前位于洛阳。")

    assert len(conflicts) == 1
    assert conflicts[0].severity == "hard"
    assert conflicts[0].category == "location"
    assert conflicts[0].memory_ids == [memory.id]
