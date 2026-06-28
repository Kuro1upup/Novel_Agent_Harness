"""Research orchestration, source evidence extraction and indexing."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from novel_harness.agents import ResearchAgent
from novel_harness.models import EvidenceSnippet, ResearchNote, utc_now
from novel_harness.providers.content import ContentFetcher, ContentFetchError
from novel_harness.providers.embedding import EmbeddingProvider
from novel_harness.providers.objectstore import ObjectStore
from novel_harness.providers.vectorstore import VectorRecord, VectorStore
from novel_harness.storage.repositories import Repositories


class ResearchService:
    def __init__(
        self,
        session: Session,
        agent: ResearchAgent,
        *,
        content_fetcher: ContentFetcher | None = None,
        object_store: ObjectStore | None = None,
        vector_store: VectorStore | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        max_fetches: int = 5,
    ) -> None:
        self.repositories = Repositories(session)
        self.agent = agent
        self.content_fetcher = content_fetcher
        self.object_store = object_store
        self.vector_store = vector_store
        self.embedding_provider = embedding_provider
        self.max_fetches = max_fetches

    async def research(
        self,
        project_id: str,
        topic: str,
        *,
        historical_context: str = "",
        keywords: Sequence[str] | None = None,
    ) -> list[ResearchNote]:
        project = self.repositories.projects.require(project_id)
        notes = await self.agent.research(
            genre=project.genre,
            historical_context=historical_context or (project.sub_genre or ""),
            keywords=keywords,
            story_need=topic,
            project_id=project_id,
        )
        uploaded_keys: list[str] = []
        indexed_ids: list[str] = []
        try:
            notes, uploaded_keys = self._fetch_evidence(notes, topic)
            notes = self._mark_corroboration(notes)
            indexed_ids = self._index_notes(notes)
            for note in notes:
                self.repositories.research.add(note)
        except Exception:
            if self.vector_store is not None and indexed_ids:
                try:
                    self.vector_store.delete(project_id=project_id, ids=indexed_ids)
                except Exception:
                    pass
            if self.object_store is not None:
                for key in uploaded_keys:
                    try:
                        self.object_store.remove(key)
                    except Exception:
                        pass
            raise
        return notes

    def _fetch_evidence(
        self, notes: list[ResearchNote], topic: str
    ) -> tuple[list[ResearchNote], list[str]]:
        if self.content_fetcher is None:
            return notes, []
        output: list[ResearchNote] = []
        uploaded: list[str] = []
        fetched_count = 0
        for note in notes:
            if note.verification_status == "mock" or fetched_count >= self.max_fetches:
                output.append(note)
                continue
            fetched_count += 1
            try:
                page = self.content_fetcher.fetch(str(note.source_url))
                if _looks_like_access_challenge(
                    final_url=page.final_url,
                    title=page.title,
                    content=page.content,
                ):
                    gaps = list(dict.fromkeys([*note.needs_further_research, topic]))
                    output.append(
                        note.model_copy(
                            update={
                                "source_url": page.final_url,
                                "source_title": page.title or note.source_title,
                                "verification_status": "fetch_failed",
                                "uncertainty": "来源返回验证码或访问验证页面，未取得正文",
                                "needs_further_research": gaps,
                            }
                        )
                    )
                    continue
                digest = hashlib.sha256(page.content.encode("utf-8")).hexdigest()
                evidence = _extract_evidence(
                    page.content,
                    query=f"{topic} {note.query}",
                    source_url=page.final_url,
                )
                object_key: str | None = None
                if self.object_store is not None:
                    object_key = f"projects/{note.project_id}/research/{note.id}/{digest}.txt"
                    self.object_store.put_bytes(
                        object_key,
                        page.content.encode("utf-8"),
                        content_type="text/plain; charset=utf-8",
                    )
                    uploaded.append(object_key)
                gaps = list(note.needs_further_research)
                uncertainty = note.uncertainty
                status = "fetched"
                if not evidence:
                    status = "fetch_failed"
                    gaps.append(topic)
                    uncertainty = "已抓取来源，但未提取到与研究主题直接相关的证据片段"
                output.append(
                    note.model_copy(
                        update={
                            "source_url": page.final_url,
                            "source_title": page.title or note.source_title,
                            "evidence_snippets": evidence,
                            "verification_status": status,
                            "source_content_hash": digest,
                            "source_object_key": object_key,
                            "source_retrieved_at": utc_now(),
                            "uncertainty": uncertainty,
                            "needs_further_research": list(dict.fromkeys(gaps)),
                        }
                    )
                )
            except ContentFetchError as exc:
                gaps = list(dict.fromkeys([*note.needs_further_research, topic]))
                output.append(
                    note.model_copy(
                        update={
                            "verification_status": "fetch_failed",
                            "uncertainty": f"来源正文抓取失败：{type(exc).__name__}",
                            "needs_further_research": gaps,
                        }
                    )
                )
        return output, uploaded

    @staticmethod
    def _mark_corroboration(notes: list[ResearchNote]) -> list[ResearchNote]:
        results: list[ResearchNote] = []
        for index, note in enumerate(notes):
            own_text = " ".join(item.text for item in note.evidence_snippets)
            own_shingles = _shingles(own_text)
            own_domain = urlparse(str(note.source_url)).hostname
            corroborating: list[str] = []
            if own_shingles:
                for other_index, other in enumerate(notes):
                    if other_index == index or not other.evidence_snippets:
                        continue
                    other_domain = urlparse(str(other.source_url)).hostname
                    if own_domain and other_domain and own_domain == other_domain:
                        continue
                    other_shingles = _shingles(
                        " ".join(item.text for item in other.evidence_snippets)
                    )
                    denominator = max(min(len(own_shingles), len(other_shingles)), 1)
                    overlap = len(own_shingles & other_shingles) / denominator
                    if overlap >= 0.08:
                        corroborating.append(str(other.source_url))
            results.append(
                note.model_copy(
                    update={
                        "corroborating_urls": list(dict.fromkeys(corroborating)),
                        "verification_status": (
                            "corroborated" if corroborating else note.verification_status
                        ),
                    }
                )
            )
        return results

    def _index_notes(self, notes: list[ResearchNote]) -> list[str]:
        if self.vector_store is None or self.embedding_provider is None:
            return []
        rows: list[tuple[ResearchNote, int, str, str]] = []
        for note in notes:
            if note.verification_status not in {"fetched", "corroborated"}:
                continue
            snippets = [item.text for item in note.evidence_snippets]
            for ordinal, text in enumerate(snippets):
                if text.strip():
                    rows.append(
                        (
                            note,
                            ordinal,
                            text,
                            hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        )
                    )
        if not rows:
            return []
        vectors = self.embedding_provider.embed_documents([row[2] for row in rows])
        records = [
            VectorRecord(
                id=f"research:{note.id}:{ordinal}",
                project_id=note.project_id,
                source_id=note.id,
                source_type="research",
                chunk_ordinal=ordinal,
                content_hash=content_hash,
                embedding=vector,
                metadata={
                    "preview": text[:1200],
                    "source_url": str(note.source_url),
                    "source_title": note.source_title,
                    "verification_status": note.verification_status,
                    "credibility_score": note.credibility_score,
                },
            )
            for (note, ordinal, text, content_hash), vector in zip(rows, vectors, strict=True)
        ]
        self.vector_store.upsert(records)
        return [record.id for record in records]


def _extract_evidence(
    content: str,
    *,
    query: str,
    source_url: str,
    limit: int = 3,
) -> list[EvidenceSnippet]:
    stopwords = {
        "资料",
        "研究",
        "历史",
        "来源",
        "相关",
        "信息",
        "考古资料",
    }
    keywords = {
        token.lower()
        for token in re.findall(r"[\u4e00-\u9fff]{2,8}|[A-Za-z0-9_-]{3,}", query)
        if token.lower() not in stopwords
    }
    candidates = [
        segment.strip()
        for segment in re.split(r"\n+|(?<=[。！？!?；;])", content)
        if 30 <= len(segment.strip()) <= 2000
    ]
    scored: list[tuple[int, int, str]] = []
    for position, segment in enumerate(candidates):
        lowered = segment.lower()
        score = sum(keyword in lowered for keyword in keywords)
        if score:
            scored.append((score, -position, segment))
    scored.sort(reverse=True)
    snippets: list[EvidenceSnippet] = []
    seen: set[str] = set()
    for _, negative_position, text in scored:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        snippets.append(
            EvidenceSnippet(
                text=text,
                source_url=source_url,
                locator=f"text-segment:{-negative_position + 1}",
                content_hash=digest,
            )
        )
        if len(snippets) >= limit:
            break
    return snippets


def _shingles(text: str, size: int = 4) -> set[str]:
    normalized = re.sub(r"\W+", "", text.lower())
    return {normalized[index : index + size] for index in range(max(len(normalized) - size + 1, 0))}


def _looks_like_access_challenge(
    *,
    final_url: str,
    title: str | None,
    content: str,
) -> bool:
    url = final_url.lower()
    normalized_title = (title or "").strip().lower()
    content_prefix = content[:2000].lower()
    url_markers = ("captcha", "/challenge", "verifycaptcha", "wappass.baidu.com")
    challenge_markers = (
        "安全验证",
        "访问验证",
        "人机验证",
        "滑动验证",
        "verify you are human",
        "checking your browser",
        "attention required",
        "access denied",
    )
    if any(marker in url for marker in url_markers):
        return True
    if any(marker in normalized_title for marker in challenge_markers):
        return True
    return len(content) < 5000 and any(marker in content_prefix for marker in challenge_markers)
