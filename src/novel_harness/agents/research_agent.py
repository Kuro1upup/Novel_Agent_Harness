"""Search-backed research synthesis."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from urllib.parse import urlparse

from novel_harness.models.research import ResearchNote

from ._base import (
    as_dict,
    call_provider,
    call_search,
    format_prompt,
    load_prompt,
    make_model,
    text_value,
    unique_strings,
    utcnow,
)


class ResearchAgent:
    def __init__(self, search_provider: Any, llm_provider: Any | None = None) -> None:
        self.search_provider = search_provider
        self.llm_provider = llm_provider

    @staticmethod
    def build_queries(
        genre: str,
        historical_context: str = "",
        keywords: Sequence[str] | None = None,
        story_need: str = "",
    ) -> list[str]:
        terms = [genre, historical_context, *(keywords or ()), story_need]
        core = " ".join(term.strip() for term in terms if term and term.strip())
        if not core:
            raise ValueError("research requires a genre, context, keyword, or story need")
        queries = [
            core,
            f"{core} 史料 可信来源",
            f"{core} 日常生活 制度 地理",
        ]
        return unique_strings(queries, limit=3)

    async def research(
        self,
        genre: str,
        historical_context: str = "",
        keywords: Sequence[str] | None = None,
        story_need: str = "",
        *,
        project_id: str = "default",
        max_results: int = 5,
    ) -> list[ResearchNote]:
        notes: list[ResearchNote] = []
        seen_urls: set[str] = set()
        for query in self.build_queries(genre, historical_context, keywords, story_need):
            results = await call_search(self.search_provider, query, limit=max_results)
            for result in results:
                data = as_dict(result)
                title = text_value(result, "title", "source_title", default="未命名来源")
                url = text_value(result, "url", "source_url")
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)
                content = text_value(result, "content", "snippet", "summary", "text")
                if not content:
                    content = "搜索结果未提供摘要，需要打开来源核验。"
                score = data.get("credibility_score")
                try:
                    score = (
                        max(0.0, min(float(score), 1.0))
                        if score is not None
                        else _source_credibility(url)
                    )
                except (TypeError, ValueError):
                    score = 0.5
                source_type = text_value(
                    result,
                    "source_type",
                    "engine",
                    "source",
                    default="web",
                )
                metadata = data.get("metadata", {})
                is_mock = source_type == "mock" or (
                    isinstance(metadata, dict) and metadata.get("mock") is True
                )
                note_data = {
                    "project_id": project_id,
                    "topic": story_need or historical_context or genre,
                    "query": query,
                    "source_title": title,
                    "source_url": url,
                    "source_type": source_type,
                    "credibility_score": 0.0 if is_mock else score,
                    "extracted_facts": [content],
                    "writing_implications": [
                        f"可将“{content[:80]}”作为场景细节候选；采用前须回到原始来源核验。"
                    ],
                    "contradictions": (
                        ["Mock 搜索内容不是外部事实，仅用于流程测试"]
                        if is_mock
                        else ([] if url else ["缺少可追溯 URL，当前信息仅作线索"])
                    ),
                    "uncertainty": (
                        "Mock 搜索结果未经外部来源验证"
                        if is_mock
                        else ("当前仅保存搜索摘要，尚未访问原文交叉核验" if url else "来源不可追溯")
                    ),
                    "needs_further_research": (
                        [query] if is_mock or not url or score < 0.7 else []
                    ),
                    "verification_status": "mock" if is_mock else "snippet_only",
                    "created_at": utcnow(),
                }
                notes.append(make_model(ResearchNote, note_data))
        if self.llm_provider is None or not notes:
            return notes

        # Synthesis is optional; search results remain the source of truth.
        prompt = format_prompt(
            load_prompt("research_agent"),
            {
                "genre": genre,
                "historical_context": historical_context,
                "story_need": story_need,
                "search_notes": notes,
            },
        )
        # Providers commonly support one object, not a generic list schema.  A
        # synthesis failure therefore must not discard traceable search notes.
        try:
            synthesized = await call_provider(self.llm_provider, prompt=prompt)
        except Exception:
            return notes
        payload = as_dict(synthesized)
        rows = payload.get("notes") if payload else None
        if not isinstance(rows, list):
            return notes
        parsed: list[ResearchNote] = []
        for row in rows:
            try:
                parsed.append(ResearchNote.model_validate(row))
            except Exception:
                continue
        return parsed or notes

    async def run(self, **kwargs: Any) -> list[ResearchNote]:
        return await self.research(**kwargs)


def _source_credibility(url: str) -> float:
    """Estimate source quality separately from a search engine's relevance score."""

    hostname = (urlparse(url).hostname or "").lower()
    if not hostname:
        return 0.3
    if hostname.endswith((".gov.cn", ".gov", ".edu.cn", ".edu")):
        return 0.85
    if any(name in hostname for name in ("baike.baidu", "wikipedia.org")):
        return 0.6
    if any(
        name in hostname
        for name in (
            "zhidao.baidu",
            "wenku.baidu",
            "baijiahao.baidu",
            "weixin.qq",
            "zhihu.com",
            "csdn.net",
        )
    ):
        return 0.35
    return 0.5
