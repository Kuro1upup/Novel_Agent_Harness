import pytest

from novel_harness.config import Settings
from novel_harness.exceptions import ConfigurationError
from novel_harness.providers import (
    build_cache_provider,
    build_embedding_provider,
    build_llm_provider,
    build_search_provider,
)
from novel_harness.providers.cache import (
    FailOpenCacheProvider,
    NullCacheProvider,
)
from novel_harness.providers.embedding import OpenAICompatibleEmbeddingProvider
from novel_harness.providers.llm import OpenAICompatibleLLMProvider
from novel_harness.providers.search import SearXNGSearchProvider


def test_qwen_embedding_factory_uses_requested_model_and_dimension() -> None:
    provider = build_embedding_provider(
        Settings(
            embedding_provider="qwen",
            qwen_api_key="qwen-secret",
        )
    )
    assert isinstance(provider, OpenAICompatibleEmbeddingProvider)
    assert provider.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert provider.model == "text-embedding-v4"
    assert provider.dimension == 1024


def test_deepseek_factory_uses_v4_flash_and_json_mode() -> None:
    provider = build_llm_provider(
        Settings(
            llm_provider="openai_compatible",
            deepseek_api_key="deepseek-secret",
        )
    )
    assert isinstance(provider, OpenAICompatibleLLMProvider)
    assert provider.base_url == "https://api.deepseek.com"
    assert provider.model == "deepseek-v4-flash"
    assert provider.supports_json_schema is False


def test_real_model_factories_require_keys() -> None:
    with pytest.raises(ConfigurationError, match="QWEN_API_KEY"):
        build_embedding_provider(Settings(embedding_provider="qwen", qwen_api_key=""))
    with pytest.raises(ConfigurationError, match="DEEPSEEK_API_KEY"):
        build_llm_provider(
            Settings(
                llm_provider="openai_compatible",
                deepseek_api_key="",
                llm_api_key="",
            )
        )


def test_searxng_is_the_default_search_provider() -> None:
    provider = build_search_provider(Settings())

    assert isinstance(provider, SearXNGSearchProvider)
    assert provider.base_url == "https://searxng.dsppt.site"


def test_cache_factory_supports_redis_and_disabled_mode() -> None:
    assert isinstance(build_cache_provider(Settings()), FailOpenCacheProvider)
    assert isinstance(
        build_cache_provider(Settings(cache_provider="none")),
        NullCacheProvider,
    )
