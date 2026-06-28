"""Provider construction from application settings."""

from __future__ import annotations

from novel_harness.config import Settings
from novel_harness.exceptions import ConfigurationError

from .cache import (
    CacheProvider,
    FailOpenCacheProvider,
    NullCacheProvider,
    RedisCacheProvider,
)
from .content import ContentFetcher, HttpContentFetcher
from .embedding import (
    DeterministicEmbeddingProvider,
    EmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
)
from .llm import LLMProvider, MockLLMProvider, OpenAICompatibleLLMProvider
from .objectstore import MinIOObjectStore, ObjectStore
from .search import MockSearchProvider, SearchProvider, SearXNGSearchProvider
from .vectorstore import MilvusVectorStore, VectorStore


def build_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "mock":
        return MockLLMProvider()
    api_key = settings.deepseek_api_key or settings.llm_api_key
    if not api_key:
        raise ConfigurationError("DEEPSEEK_API_KEY is required when LLM_PROVIDER=openai_compatible")
    return OpenAICompatibleLLMProvider(
        base_url=settings.llm_base_url,
        api_key=api_key,
        model=settings.llm_model,
        timeout=settings.request_timeout_seconds,
        max_retries=settings.provider_max_retries,
        supports_json_schema=settings.llm_supports_json_schema,
    )


def build_cache_provider(settings: Settings) -> CacheProvider:
    if settings.cache_provider == "none":
        return NullCacheProvider()
    return FailOpenCacheProvider(
        RedisCacheProvider(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password,
            database=settings.redis_database,
            socket_timeout=min(settings.request_timeout_seconds, 2.0),
        )
    )


def build_search_provider(settings: Settings) -> SearchProvider:
    if settings.search_provider == "mock":
        return MockSearchProvider()
    return SearXNGSearchProvider(
        base_url=settings.searxng_base_url,
        timeout=settings.request_timeout_seconds,
        max_retries=settings.provider_max_retries,
    )


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "deterministic":
        return DeterministicEmbeddingProvider(settings.embedding_dimension)
    if not settings.qwen_api_key:
        raise ConfigurationError("QWEN_API_KEY is required when EMBEDDING_PROVIDER=qwen")
    return OpenAICompatibleEmbeddingProvider(
        base_url=settings.embedding_base_url,
        api_key=settings.qwen_api_key,
        model=settings.embedding_model,
        dimension=settings.embedding_dimension,
        timeout=settings.request_timeout_seconds,
        max_retries=settings.provider_max_retries,
        max_batch_size=10,
    )


def build_content_fetcher(settings: Settings) -> ContentFetcher:
    return HttpContentFetcher(
        timeout=settings.request_timeout_seconds,
        max_retries=settings.provider_max_retries,
        max_response_bytes=settings.research_fetch_max_bytes,
    )


def build_object_store(settings: Settings) -> ObjectStore:
    return MinIOObjectStore(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
        bucket=settings.minio_bucket,
    )


def build_vector_store(settings: Settings) -> VectorStore:
    return MilvusVectorStore(
        host=settings.milvus_host,
        port=settings.milvus_port,
        collection_name=settings.milvus_collection,
        dimension=settings.embedding_dimension,
    )
