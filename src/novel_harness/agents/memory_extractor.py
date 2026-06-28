"""Extract durable, attributable memories from an accepted chapter."""

from __future__ import annotations

import re
from typing import Any

from novel_harness.models import (
    MemoryCandidate,
    MemoryExtraction,
    StoryBible,
)

from ._base import call_provider, format_prompt, load_prompt


class MemoryExtractor:
    def __init__(self, llm_provider: Any | None = None) -> None:
        self.llm_provider = llm_provider

    async def run(
        self,
        draft: str,
        bible: StoryBible,
        *,
        draft_id: str,
    ) -> MemoryExtraction:
        if not draft.strip():
            raise ValueError("accepted draft body is required")
        baseline = self._deterministic(draft, draft_id=draft_id)
        if self.llm_provider is None:
            return baseline
        prompt = format_prompt(
            load_prompt("memory_extractor"),
            {
                "accepted_chapter": draft[:50_000],
                "story_bible": bible.model_dump(mode="json"),
                "deterministic_baseline": baseline.model_dump(mode="json"),
            },
        )
        extracted = await call_provider(
            self.llm_provider,
            prompt=prompt,
            response_model=MemoryExtraction,
        )
        return self._normalize(extracted, baseline, draft_id=draft_id)

    @staticmethod
    def _deterministic(draft: str, *, draft_id: str) -> MemoryExtraction:
        normalized = re.sub(r"\s+", " ", draft).strip()
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[。！？!?])", normalized)
            if sentence.strip()
        ]
        selected = sentences[:2]
        if len(sentences) > 2:
            selected.append(sentences[-1])
        summary = "".join(selected)[:1000] or normalized[:1000]
        return MemoryExtraction(
            summary=summary,
            memories=[
                MemoryCandidate(
                    kind="chapter_summary",
                    subject=draft_id,
                    predicate="summary",
                    value=summary,
                    statement=summary,
                    confidence=1.0,
                    keywords=_keywords(summary),
                )
            ],
        )

    @staticmethod
    def _normalize(
        extracted: MemoryExtraction,
        baseline: MemoryExtraction,
        *,
        draft_id: str,
    ) -> MemoryExtraction:
        rows: list[MemoryCandidate] = []
        seen: set[tuple[str, str, str, str]] = set()
        chapter_summary = MemoryCandidate(
            kind="chapter_summary",
            subject=draft_id,
            predicate="summary",
            value=extracted.summary,
            statement=extracted.summary,
            confidence=1.0,
            keywords=_keywords(extracted.summary),
        )
        for index, candidate in enumerate([chapter_summary, *extracted.memories]):
            if index > 0 and candidate.kind == "chapter_summary":
                continue
            if candidate.confidence < 0.5:
                continue
            key = (
                candidate.kind,
                candidate.subject.strip().lower(),
                candidate.predicate.strip().lower(),
                candidate.statement.strip().lower(),
            )
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                candidate.model_copy(
                    update={
                        "subject": candidate.subject.strip(),
                        "predicate": candidate.predicate.strip(),
                        "value": candidate.value.strip(),
                        "statement": candidate.statement.strip(),
                        "aliases": _unique(candidate.aliases, 20),
                        "keywords": _unique(
                            [*candidate.keywords, *_keywords(candidate.statement)],
                            30,
                        ),
                    }
                )
            )
            if len(rows) >= 200:
                break
        return MemoryExtraction(
            summary=extracted.summary.strip() or baseline.summary,
            memories=rows,
        )


def _keywords(text: str) -> list[str]:
    return _unique(
        re.findall(r"[\u4e00-\u9fff]{2,8}|[A-Za-z0-9_-]{3,}", text),
        20,
    )


def _unique(values: list[str], limit: int) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        output.append(cleaned)
        if len(output) >= limit:
            break
    return output
