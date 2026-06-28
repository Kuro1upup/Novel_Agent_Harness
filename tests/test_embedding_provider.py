from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from novel_harness.exceptions import ProviderError
from novel_harness.providers.embedding import (
    EmbeddingConfigurationError,
    EmbeddingResponseError,
    EmbeddingTransportError,
    OpenAICompatibleEmbeddingProvider,
)


def _provider(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    dimension: int = 3,
    max_retries: int = 0,
) -> OpenAICompatibleEmbeddingProvider:
    return OpenAICompatibleEmbeddingProvider(
        base_url="https://embeddings.example.test/v1/",
        api_key="secret",
        model="example-embedding",
        dimension=dimension,
        timeout=4.0,
        max_retries=max_retries,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_embeddings_request_and_response_preserve_input_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://embeddings.example.test/v1/embeddings"
        assert request.headers["authorization"] == "Bearer secret"
        assert request.headers["accept"] == "application/json"
        assert request.read()
        payload = json.loads(request.content)
        assert payload == {
            "model": "example-embedding",
            "input": ["first", "second"],
            "dimensions": 3,
            "encoding_format": "float",
        }
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [4, 5.5, 6]},
                    {"index": 0, "embedding": [1, 2, 3]},
                ]
            },
        )

    provider = _provider(handler)

    assert provider.dimension == 3
    assert provider.embed_documents(["first", "second"]) == [
        [1.0, 2.0, 3.0],
        [4.0, 5.5, 6.0],
    ]


def test_empty_input_does_not_issue_a_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Unexpected request: {request.url}")

    assert _provider(handler).embed_documents([]) == []


def test_qwen_batch_limit_splits_large_input() -> None:
    batch_sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        batch_sizes.append(len(payload["input"]))
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": index, "embedding": [1, 2, 3]}
                    for index, _ in enumerate(payload["input"])
                ]
            },
        )

    vectors = _provider(handler).embed_documents([f"text-{index}" for index in range(11)])

    assert batch_sizes == [10, 1]
    assert len(vectors) == 11


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ([{"index": 0, "embedding": [1, 2, 3]}], "1 vectors for 2 inputs"),
        (
            [
                {"index": 0, "embedding": [1, 2, 3]},
                {"index": 0, "embedding": [4, 5, 6]},
            ],
            "duplicate index 0",
        ),
        (
            [
                {"index": 0, "embedding": [1, 2, 3]},
                {"index": 2, "embedding": [4, 5, 6]},
            ],
            "invalid index",
        ),
        (
            [
                {"index": 0, "embedding": [1, 2]},
                {"index": 1, "embedding": [4, 5, 6]},
            ],
            "dimension 2; expected 3",
        ),
        (
            [
                {"index": 0, "embedding": [1, True, 3]},
                {"index": 1, "embedding": [4, 5, 6]},
            ],
            "is not numeric",
        ),
        (
            [
                {"index": 0, "embedding": [1, float("inf"), 3]},
                {"index": 1, "embedding": [4, 5, 6]},
            ],
            "is not finite",
        ),
    ],
)
def test_rejects_invalid_embedding_responses(
    data: list[dict[str, object]],
    message: str,
) -> None:
    provider = _provider(lambda request: httpx.Response(200, content=json.dumps({"data": data})))

    with pytest.raises(EmbeddingResponseError, match=message):
        provider.embed_documents(["first", "second"])


def test_retries_transient_http_errors() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, text="temporarily unavailable")
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1, 2, 3]}]})

    provider = _provider(handler, max_retries=1)

    assert provider.embed_query("query") == [1.0, 2.0, 3.0]
    assert attempts == 2


def test_wraps_transport_and_invalid_json_errors() -> None:
    unavailable = _provider(lambda request: httpx.Response(401, text="invalid key"))
    invalid_json = _provider(lambda request: httpx.Response(200, text="not-json"))

    with pytest.raises(EmbeddingTransportError, match="HTTP 401"):
        unavailable.embed_query("query")
    with pytest.raises(EmbeddingResponseError, match="invalid JSON"):
        invalid_json.embed_query("query")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"base_url": "", "model": "model", "dimension": 3},
        {"base_url": "https://example.test/v1", "model": "", "dimension": 3},
        {"base_url": "https://example.test/v1", "model": "model", "dimension": 0},
        {
            "base_url": "https://example.test/v1",
            "model": "model",
            "dimension": 3,
            "timeout": 0,
        },
        {
            "base_url": "https://example.test/v1",
            "model": "model",
            "dimension": 3,
            "max_retries": -1,
        },
        {
            "base_url": "https://example.test/v1",
            "model": "model",
            "dimension": 3,
            "max_batch_size": 0,
        },
    ],
)
def test_rejects_invalid_configuration(kwargs: dict[str, Any]) -> None:
    with pytest.raises(EmbeddingConfigurationError):
        OpenAICompatibleEmbeddingProvider(**kwargs)


def test_all_embedding_failures_use_shared_provider_error() -> None:
    assert issubclass(EmbeddingConfigurationError, ProviderError)
    assert issubclass(EmbeddingTransportError, ProviderError)
    assert issubclass(EmbeddingResponseError, ProviderError)
