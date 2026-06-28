"""Provider-neutral embedding contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from novel_harness.exceptions import ProviderError


class EmbeddingError(ProviderError):
    """Base embedding provider error."""


class EmbeddingConfigurationError(EmbeddingError):
    """Embedding provider configuration is invalid."""


class EmbeddingTransportError(EmbeddingError):
    """The remote embedding provider could not be reached or rejected a request."""


class EmbeddingResponseError(EmbeddingError):
    """The embedding provider returned a malformed or incompatible response."""


class EmbeddingProvider(ABC):
    """Synchronous text-embedding interface."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Number of floats returned for each text."""

    @abstractmethod
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed documents while preserving input order."""

    def embed_query(self, text: str) -> list[float]:
        """Embed one query using the same vector space as documents."""

        return self.embed_documents([text])[0]
