"""Conservative source-overlap checks for generated prose."""

from __future__ import annotations

import re
from dataclasses import dataclass


def _normalize(text: str) -> str:
    return re.sub(r"\s+|[，。！？、；：“”‘’（）《》,.!?;:'\"()\[\]{}<>]", "", text)


def _longest_common_substring(left: str, right: str) -> int:
    if not left or not right:
        return 0
    previous = [0] * (len(right) + 1)
    best = 0
    for left_char in left:
        current = [0]
        for index, right_char in enumerate(right, start=1):
            size = previous[index - 1] + 1 if left_char == right_char else 0
            current.append(size)
            best = max(best, size)
        previous = current
    return best


def _ngrams(text: str, size: int = 5) -> set[str]:
    if len(text) < size:
        return {text} if text else set()
    return {text[index : index + size] for index in range(len(text) - size + 1)}


@dataclass(frozen=True, slots=True)
class OriginalityReport:
    passed: bool
    longest_contiguous_match: int
    max_ngram_overlap: float
    matched_source_index: int | None


def check_originality(
    draft: str,
    sources: list[str],
    *,
    max_contiguous_chars: int = 24,
    max_ngram_overlap: float = 0.35,
) -> OriginalityReport:
    """Flag substantial reuse; this is a safety signal, not a legal conclusion."""

    normalized_draft = _normalize(draft)
    draft_ngrams = _ngrams(normalized_draft)
    longest = 0
    overlap = 0.0
    source_index: int | None = None
    for index, source in enumerate(sources):
        normalized_source = _normalize(source)
        contiguous = _longest_common_substring(normalized_draft, normalized_source)
        source_ngrams = _ngrams(normalized_source)
        denominator = max(len(draft_ngrams), 1)
        ratio = len(draft_ngrams & source_ngrams) / denominator
        if contiguous > longest or ratio > overlap:
            source_index = index
        longest = max(longest, contiguous)
        overlap = max(overlap, ratio)
    passed = longest <= max_contiguous_chars and overlap <= max_ngram_overlap
    return OriginalityReport(passed, longest, overlap, source_index)
