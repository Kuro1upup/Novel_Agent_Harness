"""Priority-aware context assembly."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from novel_harness.providers.embedding import EmbeddingProvider
from novel_harness.providers.objectstore import ObjectStore, ObjectStoreError
from novel_harness.providers.vectorstore import VectorMatch, VectorStore

if TYPE_CHECKING:
    from novel_harness.storage.repositories import Repositories


@dataclass(frozen=True, slots=True)
class RetrievalFragment:
    """One project-scoped, budgeted piece of retrieved context."""

    source_id: str
    source_type: str
    content: str
    score: float
    content_hash: str
    chunk_ordinal: int
    metadata: Mapping[str, Any] = field(default_factory=dict)
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class RetrievalContext:
    """Structured result of one semantic context lookup."""

    project_id: str
    query: str
    fragments: tuple[RetrievalFragment, ...]
    total_characters: int
    truncated: bool = False

    def sections(self) -> dict[str, list[str]]:
        """Group fragment contents for use with :meth:`ContextManager.assemble`."""

        grouped: dict[str, list[str]] = {}
        for fragment in self.fragments:
            grouped.setdefault(fragment.source_type, []).append(fragment.content)
        return grouped


class ContextManager:
    """Build bounded prompts without dropping hard canon before soft context."""

    DEFAULT_PRIORITY = (
        "story_bible",
        "current_story",
        "characters",
        "style",
        "memory",
        "research",
    )
    RETRIEVAL_PRIORITY = (
        "story_bible",
        "current_story",
        "chapter",
        "character",
        "characters",
        "style",
        "memory",
        "research",
        "document",
    )

    def __init__(
        self,
        max_characters: int = 24_000,
        *,
        vector_store: VectorStore | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        object_store: ObjectStore | None = None,
        repositories: Repositories | None = None,
    ) -> None:
        if max_characters < 1:
            raise ValueError("max_characters must be positive")
        self.max_characters = max_characters
        self.vector_store = vector_store
        self.embedding_provider = embedding_provider
        self.object_store = object_store
        self.repositories = repositories

    def assemble(
        self,
        sections: Mapping[str, str | Iterable[str]],
        *,
        priority: tuple[str, ...] | None = None,
    ) -> str:
        order = priority or self.DEFAULT_PRIORITY
        remaining = self.max_characters
        output: list[str] = []
        known = set(order)
        keys = [*order, *(key for key in sections if key not in known)]
        for key in keys:
            if key not in sections or remaining <= 0:
                continue
            raw = sections[key]
            text = raw if isinstance(raw, str) else "\n".join(str(item) for item in raw)
            text = text.strip()
            if not text:
                continue
            header = f"## {key}\n"
            allowance = max(remaining - len(header), 0)
            if allowance <= 0:
                break
            clipped = text[:allowance]
            block = header + clipped
            output.append(block)
            remaining -= len(block) + 2
        return "\n\n".join(output)

    def retrieve(
        self,
        project_id: str,
        query: str,
        *,
        source_types: Sequence[str] | None = None,
        limit: int = 10,
        priority: Sequence[str] | None = None,
    ) -> RetrievalContext:
        """Retrieve, resolve and budget semantic context for exactly one project.

        Vector metadata is used as the canonical fallback. Document matches are
        resolved from their project-owned repository record and parsed object
        whenever both dependencies are available.
        """

        if not project_id.strip():
            raise ValueError("project_id must not be empty")
        if not query.strip():
            raise ValueError("query must not be empty")
        if limit < 1:
            raise ValueError("limit must be positive")
        if self.vector_store is None or self.embedding_provider is None:
            raise RuntimeError("vector_store and embedding_provider are required for retrieval")

        requested_types = tuple(dict.fromkeys(source_types)) if source_types else None
        vector = self.embedding_provider.embed_query(query)
        matches = self.vector_store.search(
            project_id=project_id,
            vector=vector,
            limit=limit,
            source_types=requested_types,
        )
        allowed_types = set(requested_types) if requested_types else None
        rank = {
            source_type: index
            for index, source_type in enumerate(priority or self.RETRIEVAL_PRIORITY)
        }
        ordered = sorted(
            matches,
            key=lambda match: (
                rank.get(match.source_type, len(rank)),
                -match.score,
                match.chunk_ordinal,
            ),
        )

        fragments: list[RetrievalFragment] = []
        seen_hashes: set[str] = set()
        seen_content: set[str] = set()
        remaining = self.max_characters
        was_truncated = False
        for match in ordered:
            # Do not trust a provider implementation to have applied its filter.
            if match.project_id != project_id:
                continue
            if allowed_types is not None and match.source_type not in allowed_types:
                continue
            if match.source_type == "research" and not _is_trusted_research_match(match):
                continue

            content = self._resolve_content(project_id, match)
            if not content:
                continue
            normalized = " ".join(content.split())
            if not normalized:
                continue
            is_duplicate_hash = bool(match.content_hash and match.content_hash in seen_hashes)
            if is_duplicate_hash or normalized in seen_content:
                continue
            if remaining <= 0:
                was_truncated = True
                break

            clipped = content[:remaining]
            fragment_truncated = len(clipped) < len(content)
            fragments.append(
                RetrievalFragment(
                    source_id=match.source_id,
                    source_type=match.source_type,
                    content=clipped,
                    score=match.score,
                    content_hash=match.content_hash,
                    chunk_ordinal=match.chunk_ordinal,
                    metadata=dict(match.metadata),
                    truncated=fragment_truncated,
                )
            )
            if match.content_hash:
                seen_hashes.add(match.content_hash)
            seen_content.add(normalized)
            remaining -= len(clipped)
            was_truncated = was_truncated or fragment_truncated

        return RetrievalContext(
            project_id=project_id,
            query=query,
            fragments=tuple(fragments),
            total_characters=sum(len(fragment.content) for fragment in fragments),
            truncated=was_truncated,
        )

    def _resolve_content(self, project_id: str, match: VectorMatch) -> str:
        preview_value = match.metadata.get("preview")
        preview = preview_value.strip() if isinstance(preview_value, str) else ""
        if match.source_type != "document":
            return preview
        if self.repositories is None:
            return preview

        document = self.repositories.documents.get(match.source_id)
        if document is None or document.project_id != project_id:
            return ""
        if self.object_store is None or not document.parsed_object_key:
            return preview
        try:
            parsed = self.object_store.get_bytes(document.parsed_object_key).decode("utf-8")
        except (KeyError, UnicodeDecodeError, OSError, ObjectStoreError):
            return preview
        if not parsed:
            return preview

        # Current ingestion uses 1,200-character chunks with a 120-character
        # overlap. Prefer locating the stored preview so retrieval stays valid
        # if that chunking policy changes.
        start = parsed.find(preview) if preview else -1
        if start < 0:
            start = match.chunk_ordinal * 1_080
        if start >= len(parsed):
            return preview
        return parsed[start : start + 1_200].strip() or preview


def _is_trusted_research_match(match: VectorMatch) -> bool:
    status = match.metadata.get("verification_status")
    if status not in {"fetched", "corroborated"}:
        return False
    try:
        credibility = float(match.metadata.get("credibility_score", 0))
    except (TypeError, ValueError):
        return False
    if credibility < 0.5:
        return False
    source_url = str(match.metadata.get("source_url", "")).lower()
    return not any(
        marker in source_url
        for marker in ("captcha", "/challenge", "verifycaptcha", "wappass.baidu.com")
    )
