"""Dependency-free deterministic embeddings for local and test use."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections.abc import Sequence

from .base import EmbeddingConfigurationError, EmbeddingProvider

_TOKEN_PATTERN = re.compile(r"[\w]+|[^\w\s]", flags=re.UNICODE)
_CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")


class DeterministicEmbeddingProvider(EmbeddingProvider):
    """Feature-hashing embeddings.

    These vectors are stable across processes and require no model download.
    They are intended for development and deterministic tests, not as a
    substitute for a production semantic embedding model.
    """

    def __init__(self, dimension: int = 384) -> None:
        if dimension < 8:
            raise EmbeddingConfigurationError("Embedding dimension must be at least 8")
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def _embed(self, text: str) -> list[float]:
        normalized = unicodedata.normalize("NFKC", text).casefold()
        tokens = _TOKEN_PATTERN.findall(normalized)
        features = list(tokens)
        features.extend(f"{tokens[index]}::{tokens[index + 1]}" for index in range(len(tokens) - 1))
        for run in _CJK_PATTERN.findall(normalized):
            for width in (1, 2, 3):
                features.extend(
                    f"cjk:{run[index : index + width]}"
                    for index in range(max(len(run) - width + 1, 0))
                )
        vector = [0.0] * self.dimension
        for feature in features:
            digest = hashlib.blake2b(
                feature.encode("utf-8"), digest_size=16, person=b"novel-harness"
            ).digest()
            index = int.from_bytes(digest[:8], "big") % self.dimension
            sign = 1.0 if digest[8] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            return [value / norm for value in vector]
        return vector
