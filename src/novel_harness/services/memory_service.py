"""Accepted-chapter memory extraction, hybrid retrieval and consistency checks."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Any

from sqlalchemy.orm import Session

from novel_harness.agents import MemoryExtractor
from novel_harness.models import (
    MemoryConflict,
    MemoryRecord,
    MemorySearchHit,
    MemoryState,
)
from novel_harness.providers.cache import CacheProvider, NullCacheProvider
from novel_harness.providers.embedding import EmbeddingProvider
from novel_harness.providers.vectorstore import VectorRecord, VectorStore
from novel_harness.storage.repositories import Repositories

from .story_bible_service import StoryBibleService

STATEFUL_KINDS = {
    "character_state",
    "location_state",
    "item_ownership",
    "relationship",
    "knowledge",
}


class MemoryService:
    def __init__(
        self,
        session: Session,
        *,
        object_store: Any,
        vector_store: VectorStore,
        embedding_provider: EmbeddingProvider,
        extractor: MemoryExtractor,
        cache_provider: CacheProvider | None = None,
        cache_ttl_seconds: int = 900,
    ) -> None:
        self.session = session
        self.repositories = Repositories(session)
        self.object_store = object_store
        self.vector_store = vector_store
        self.embedding_provider = embedding_provider
        self.extractor = extractor
        self.cache = cache_provider or NullCacheProvider()
        self.cache_ttl_seconds = cache_ttl_seconds

    def state(self, project_id: str) -> MemoryState:
        self.repositories.projects.require(project_id)
        return self.repositories.memory_states.get(project_id)

    async def extract_accepted_draft(
        self,
        project_id: str,
        draft_id: str,
        *,
        canon_version: int | None = None,
    ) -> list[MemoryRecord]:
        self.repositories.projects.require(project_id)
        draft = self.repositories.generations.require(draft_id)
        if draft.project_id != project_id:
            raise ValueError("draft belongs to another project")
        if draft.status != "accepted":
            raise ValueError("only accepted drafts may update long-term memory")
        if not draft.object_key:
            raise ValueError("accepted draft has no object-store body")
        body = self.object_store.get_bytes(draft.object_key).decode("utf-8")
        bible = StoryBibleService(self.session).get(project_id)
        version = canon_version or self._accepted_canon_version(draft_id) or bible.version
        extraction = await self.extractor.run(body, bible, draft_id=draft_id)

        created: list[MemoryRecord] = []
        superseded: list[MemoryRecord] = []
        active = self.repositories.memories.list_active(project_id, limit=10_000)
        for candidate in extraction.memories:
            digest = hashlib.sha256(
                "\x1f".join(
                    (
                        draft_id,
                        candidate.kind,
                        candidate.subject,
                        candidate.predicate,
                        candidate.statement,
                    )
                ).encode("utf-8")
            ).hexdigest()
            existing = self.repositories.memories.get_by_hash(project_id, digest)
            if existing is not None:
                continue
            record = MemoryRecord(
                project_id=project_id,
                kind=candidate.kind,
                subject=candidate.subject,
                predicate=candidate.predicate,
                value=candidate.value,
                statement=candidate.statement,
                aliases=candidate.aliases,
                keywords=candidate.keywords,
                story_time=candidate.story_time,
                source_draft_id=draft_id,
                canon_version=version,
                confidence=candidate.confidence,
                source_hash=digest,
                metadata={"chapter_object_key": draft.object_key},
            )
            self.repositories.memories.add(record)
            created.append(record)
            if record.kind in STATEFUL_KINDS:
                for previous in active:
                    if (
                        previous.kind == record.kind
                        and previous.subject == record.subject
                        and previous.predicate == record.predicate
                        and previous.value != record.value
                        and previous.status == "active"
                    ):
                        superseded.append(previous)

        if not created:
            return self.repositories.memories.list_for_draft(draft_id)

        new_vector_ids = [f"memory:{record.id}" for record in created]
        try:
            self._index(created)
            for previous in {item.id: item for item in superseded}.values():
                self.repositories.memories.update(
                    previous.model_copy(
                        update={
                            "status": "invalidated",
                            "invalidated_reason": (f"superseded by accepted draft {draft_id}"),
                        }
                    )
                )
            if superseded:
                self.vector_store.delete(
                    project_id=project_id,
                    ids=[f"memory:{item.id}" for item in superseded],
                )
            self.repositories.memory_states.bump(project_id)
        except Exception:
            try:
                self.vector_store.delete(project_id=project_id, ids=new_vector_ids)
            except Exception:
                pass
            raise
        return created

    def search(
        self,
        project_id: str,
        query: str,
        *,
        kinds: Sequence[str] | None = None,
        limit: int = 10,
    ) -> list[MemorySearchHit]:
        self.repositories.projects.require(project_id)
        if not query.strip():
            raise ValueError("memory query must not be empty")
        if not 1 <= limit <= 100:
            raise ValueError("memory query limit must be between 1 and 100")
        state = self.repositories.memory_states.get(project_id)
        kind_tuple = tuple(sorted(set(kinds or ())))
        cache_key = self._cache_key(
            project_id,
            state.revision,
            query,
            kind_tuple,
            limit,
        )
        cached = self.cache.get_json(cache_key)
        if isinstance(cached, list):
            try:
                return [MemorySearchHit.model_validate(item) for item in cached]
            except Exception:
                pass

        active = self._effective_memories(
            self.repositories.memories.list_active(
                project_id,
                kinds=kind_tuple or None,
                limit=10_000,
            )
        )
        by_id = {memory.id: memory for memory in active}
        lexical = self._lexical_rank(query, active)
        vector = self.embedding_provider.embed_query(query)
        semantic_matches = self.vector_store.search(
            project_id=project_id,
            vector=vector,
            limit=min(max(limit * 4, 20), 200),
            source_types=["memory"],
        )
        semantic = [
            (match.source_id, match.score) for match in semantic_matches if match.source_id in by_id
        ]
        scores: dict[str, dict[str, float]] = {}
        for rank, (memory_id, score) in enumerate(semantic, start=1):
            row = scores.setdefault(
                memory_id,
                {"rrf": 0.0, "semantic": 0.0, "lexical": 0.0},
            )
            row["rrf"] += 1 / (60 + rank)
            row["semantic"] = score
        for rank, (memory_id, score) in enumerate(lexical, start=1):
            row = scores.setdefault(
                memory_id,
                {"rrf": 0.0, "semantic": 0.0, "lexical": 0.0},
            )
            row["rrf"] += 1 / (60 + rank)
            row["lexical"] = score
        ordered = sorted(
            scores,
            key=lambda memory_id: (
                scores[memory_id]["rrf"],
                scores[memory_id]["lexical"],
                scores[memory_id]["semantic"],
            ),
            reverse=True,
        )
        hits = [
            MemorySearchHit(
                memory=by_id[memory_id],
                semantic_score=scores[memory_id]["semantic"],
                lexical_score=scores[memory_id]["lexical"],
                combined_score=scores[memory_id]["rrf"],
            )
            for memory_id in ordered[:limit]
        ]
        self.cache.set_json(
            cache_key,
            [hit.model_dump(mode="json") for hit in hits],
            ttl_seconds=self.cache_ttl_seconds,
        )
        return hits

    def preflight(
        self,
        project_id: str,
        proposed_text: str,
        *,
        run_id: str | None = None,
        persist: bool = True,
    ) -> list[MemoryConflict]:
        if not proposed_text.strip():
            return []
        memories = self._effective_memories(
            self.repositories.memories.list_active(project_id, limit=10_000)
        )
        conflicts: list[MemoryConflict] = []
        for memory in memories:
            conflict = self._check_memory_against_text(
                memory,
                proposed_text,
                run_id=run_id,
            )
            if conflict is not None:
                conflicts.append(conflict)
                if persist:
                    self.repositories.memory_conflicts.add(conflict)
        return conflicts

    def invalidate(self, memory_id: str, *, reason: str) -> MemoryRecord:
        memory = self.repositories.memories.require(memory_id)
        if memory.status == "invalidated":
            return memory
        updated = memory.model_copy(update={"status": "invalidated", "invalidated_reason": reason})
        self.repositories.memories.update(updated)
        self.vector_store.delete(
            project_id=memory.project_id,
            ids=[f"memory:{memory.id}"],
        )
        self.repositories.memory_states.bump(memory.project_id)
        return updated

    async def rebuild(self, project_id: str) -> dict[str, int]:
        self.repositories.projects.require(project_id)
        existing = self.repositories.memories.list(project_id, limit=100_000)
        if existing:
            self.vector_store.delete(
                project_id=project_id,
                ids=[f"memory:{memory.id}" for memory in existing],
            )
        deleted = self.repositories.memories.delete_for_project(project_id)
        self.repositories.memory_states.bump(project_id)
        created = 0
        accepted = [
            draft
            for draft in self.repositories.generations.list(project_id, limit=100_000)
            if draft.status == "accepted"
        ]
        for draft in accepted:
            rows = await self.extract_accepted_draft(project_id, draft.id)
            created += len(rows)
        return {
            "accepted_drafts": len(accepted),
            "deleted_memories": deleted,
            "created_memories": created,
        }

    def _index(self, records: Sequence[MemoryRecord]) -> None:
        if not records:
            return
        vectors = self.embedding_provider.embed_documents([record.statement for record in records])
        self.vector_store.upsert(
            [
                VectorRecord(
                    id=f"memory:{record.id}",
                    project_id=record.project_id,
                    source_id=record.id,
                    source_type="memory",
                    chunk_ordinal=0,
                    content_hash=record.source_hash,
                    embedding=vector,
                    metadata={
                        "preview": record.statement,
                        "kind": record.kind,
                        "subject": record.subject,
                        "predicate": record.predicate,
                        "canon_version": record.canon_version,
                        "confidence": record.confidence,
                    },
                )
                for record, vector in zip(records, vectors, strict=True)
            ]
        )

    def _accepted_canon_version(self, draft_id: str) -> int | None:
        for patch in self.repositories.canon_patches.list(
            self.repositories.generations.require(draft_id).project_id,
            limit=10_000,
        ):
            if patch.draft_id == draft_id and patch.accepted_bible_version:
                return patch.accepted_bible_version
        return None

    @staticmethod
    def _effective_memories(records: Sequence[MemoryRecord]) -> list[MemoryRecord]:
        output: list[MemoryRecord] = []
        stateful_seen: set[tuple[str, str, str]] = set()
        for memory in sorted(
            records,
            key=lambda item: (item.canon_version, item.created_at),
            reverse=True,
        ):
            key = (memory.kind, memory.subject, memory.predicate)
            if memory.kind in STATEFUL_KINDS and key in stateful_seen:
                continue
            if memory.kind in STATEFUL_KINDS:
                stateful_seen.add(key)
            output.append(memory)
        return output

    @staticmethod
    def _lexical_rank(
        query: str,
        memories: Sequence[MemoryRecord],
    ) -> list[tuple[str, float]]:
        query_tokens = _tokens(query)
        if not query_tokens:
            return []
        scored: list[tuple[str, float]] = []
        for memory in memories:
            text = " ".join(
                [
                    memory.subject,
                    memory.predicate,
                    memory.value,
                    memory.statement,
                    *memory.aliases,
                    *memory.keywords,
                ]
            )
            document_tokens = _tokens(text)
            overlap = query_tokens & document_tokens
            if not overlap:
                continue
            score = len(overlap) / math.sqrt(max(len(query_tokens) * len(document_tokens), 1))
            if memory.subject.lower() in query.lower():
                score += 1.0
            scored.append((memory.id, score))
        return sorted(scored, key=lambda item: item[1], reverse=True)

    @staticmethod
    def _check_memory_against_text(
        memory: MemoryRecord,
        text: str,
        *,
        run_id: str | None,
    ) -> MemoryConflict | None:
        if memory.subject not in text:
            return None
        escaped = re.escape(memory.subject)
        if memory.kind == "location_state":
            match = re.search(
                rf"{escaped}.{{0,12}}?(?:目前)?(?:位于|身在|来到)"
                r"(?P<value>[\u4e00-\u9fffA-Za-z0-9_-]{2,20})(?=[，。；、\s]|$)",
                text,
            )
            if match and not _same_value(match.group("value"), memory.value):
                return MemoryConflict(
                    project_id=memory.project_id,
                    run_id=run_id,
                    query=text[:2000],
                    severity="hard",
                    category="location",
                    description=(
                        f"{memory.subject}的已知位置是“{memory.value}”，"
                        f"拟写内容声明为“{match.group('value')}”。"
                    ),
                    memory_ids=[memory.id],
                    suggestion="补充移动过程或修正场景地点。",
                )
        if memory.kind == "item_ownership":
            match = re.search(
                rf"(?P<owner>[\u4e00-\u9fffA-Za-z0-9_-]{{1,20}})"
                rf".{{0,8}}?(?:持有|拿着|获得){escaped}",
                text,
            )
            if match and not _same_value(match.group("owner"), memory.value):
                return MemoryConflict(
                    project_id=memory.project_id,
                    run_id=run_id,
                    query=text[:2000],
                    severity="hard",
                    category="item",
                    description=(
                        f"{memory.subject}当前由“{memory.value}”持有，"
                        f"拟写内容的持有人是“{match.group('owner')}”。"
                    ),
                    memory_ids=[memory.id],
                    suggestion="交代物品转移过程或修正持有人。",
                )
        if memory.kind == "character_state" and memory.predicate in {"age", "年龄"}:
            match = re.search(rf"{escaped}.{{0,10}}?(\d{{1,3}})\s*岁", text)
            if match and match.group(1) != memory.value:
                return MemoryConflict(
                    project_id=memory.project_id,
                    run_id=run_id,
                    query=text[:2000],
                    severity="soft",
                    category="character",
                    description=(
                        f"{memory.subject}记忆年龄为{memory.value}岁，"
                        f"拟写内容为{match.group(1)}岁。"
                    ),
                    memory_ids=[memory.id],
                    suggestion="核对故事时间跨度和生日是否已经发生。",
                )
        return None

    @staticmethod
    def _cache_key(
        project_id: str,
        revision: int,
        query: str,
        kinds: Sequence[str],
        limit: int,
    ) -> str:
        digest = hashlib.sha256(f"{query}\x1f{','.join(kinds)}\x1f{limit}".encode()).hexdigest()
        return f"novel:memory:{project_id}:r{revision}:{digest}"


def _tokens(text: str) -> set[str]:
    normalized = text.lower()
    words = set(re.findall(r"[a-z0-9_-]{2,}|[\u4e00-\u9fff]{2,8}", normalized))
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", normalized))
    words.update(chinese[index : index + 2] for index in range(max(len(chinese) - 1, 0)))
    return words


def _same_value(candidate: str, expected: str) -> bool:
    left = re.sub(r"\s+", "", candidate).lower()
    right = re.sub(r"\s+", "", expected).lower()
    return bool(left and right and (left == right or left in right or right in left))
