"""OpenAI-compatible Embeddings API provider."""

from __future__ import annotations

import math
import time
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from .base import (
    EmbeddingConfigurationError,
    EmbeddingProvider,
    EmbeddingResponseError,
    EmbeddingTransportError,
)


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    """Synchronous client for an OpenAI-compatible ``/embeddings`` endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        dimension: int,
        api_key: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 2,
        max_batch_size: int = 10,
        client: httpx.Client | None = None,
    ) -> None:
        if not base_url.strip():
            raise EmbeddingConfigurationError("Embedding base_url must not be empty")
        if not model.strip():
            raise EmbeddingConfigurationError("Embedding model must not be empty")
        if dimension <= 0:
            raise EmbeddingConfigurationError("Embedding dimension must be positive")
        if timeout <= 0:
            raise EmbeddingConfigurationError("Embedding timeout must be positive")
        if max_retries < 0:
            raise EmbeddingConfigurationError("Embedding max_retries cannot be negative")
        if max_batch_size < 1:
            raise EmbeddingConfigurationError("Embedding max_batch_size must be positive")

        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self._dimension = dimension
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_batch_size = max_batch_size
        self._client = client

    @property
    def endpoint(self) -> str:
        """Full OpenAI-compatible embeddings endpoint."""

        return f"{self.base_url}/embeddings"

    @property
    def dimension(self) -> int:
        """Configured and enforced vector dimension."""

        return self._dimension

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed ``texts`` in one request while preserving their input order."""

        if isinstance(texts, str) or any(not isinstance(text, str) for text in texts):
            raise EmbeddingConfigurationError("Embedding inputs must be a sequence of strings")
        if not texts:
            return []

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.max_batch_size):
            batch = list(texts[start : start + self.max_batch_size])
            payload: dict[str, Any] = {
                "model": self.model,
                "input": batch,
                "dimensions": self.dimension,
                "encoding_format": "float",
            }
            response = self._post_with_retry(payload, headers)
            vectors.extend(self._normalize(response, expected_count=len(batch)))
        return vectors

    def _post_with_retry(
        self,
        payload: Mapping[str, Any],
        headers: Mapping[str, str],
    ) -> Mapping[str, Any]:
        client = self._client or httpx.Client()
        owns_client = self._client is None
        try:
            for attempt in range(self.max_retries + 1):
                try:
                    response = client.post(
                        self.endpoint,
                        json=payload,
                        headers=headers,
                        timeout=self.timeout,
                    )
                    if self._is_retryable(response.status_code) and attempt < self.max_retries:
                        self._backoff(attempt, response)
                        continue
                    response.raise_for_status()
                    data = response.json()
                    if not isinstance(data, Mapping):
                        raise EmbeddingResponseError(
                            "Embedding response root must be a JSON object"
                        )
                    return data
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt >= self.max_retries:
                        raise EmbeddingTransportError(
                            f"Embedding request failed after {attempt + 1} attempts: {exc}"
                        ) from exc
                    time.sleep(min(0.25 * (2**attempt), 2.0))
                except httpx.HTTPStatusError as exc:
                    body = exc.response.text[:500]
                    raise EmbeddingTransportError(
                        f"Embedding provider returned HTTP {exc.response.status_code}: {body}"
                    ) from exc
                except ValueError as exc:
                    raise EmbeddingResponseError(
                        "Embedding provider returned invalid JSON"
                    ) from exc
        finally:
            if owns_client:
                client.close()
        raise EmbeddingTransportError("Embedding request failed without a response")

    def _normalize(
        self,
        response: Mapping[str, Any],
        *,
        expected_count: int,
    ) -> list[list[float]]:
        data = response.get("data")
        if not isinstance(data, list):
            raise EmbeddingResponseError("Embedding response is missing a data list")
        if len(data) != expected_count:
            raise EmbeddingResponseError(
                f"Embedding response returned {len(data)} vectors for {expected_count} inputs"
            )

        vectors: list[list[float] | None] = [None] * expected_count
        for position, item in enumerate(data):
            if not isinstance(item, Mapping):
                raise EmbeddingResponseError(
                    f"Embedding response data[{position}] must be an object"
                )
            index = item.get("index")
            if (
                not isinstance(index, int)
                or isinstance(index, bool)
                or index < 0
                or index >= expected_count
            ):
                raise EmbeddingResponseError(
                    f"Embedding response data[{position}] has an invalid index"
                )
            if vectors[index] is not None:
                raise EmbeddingResponseError(f"Embedding response contains duplicate index {index}")
            vectors[index] = self._normalize_vector(item.get("embedding"), index=index)

        if any(vector is None for vector in vectors):
            raise EmbeddingResponseError("Embedding response does not cover every input index")
        return [vector for vector in vectors if vector is not None]

    def _normalize_vector(self, raw: Any, *, index: int) -> list[float]:
        if not isinstance(raw, list):
            raise EmbeddingResponseError(f"Embedding at index {index} must be a JSON array")
        if len(raw) != self.dimension:
            raise EmbeddingResponseError(
                f"Embedding at index {index} has dimension {len(raw)}; expected {self.dimension}"
            )

        vector: list[float] = []
        for offset, value in enumerate(raw):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise EmbeddingResponseError(
                    f"Embedding at index {index}, offset {offset} is not numeric"
                )
            normalized = float(value)
            if not math.isfinite(normalized):
                raise EmbeddingResponseError(
                    f"Embedding at index {index}, offset {offset} is not finite"
                )
            vector.append(normalized)
        return vector

    @staticmethod
    def _is_retryable(status_code: int) -> bool:
        return status_code in {408, 409, 429} or status_code >= 500

    @staticmethod
    def _backoff(attempt: int, response: httpx.Response) -> None:
        retry_after = response.headers.get("retry-after")
        try:
            delay = min(float(retry_after), 5.0) if retry_after else 0.25 * (2**attempt)
        except ValueError:
            delay = 0.25 * (2**attempt)
        time.sleep(delay)
