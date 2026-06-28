from __future__ import annotations

import os

import pytest
from pydantic import Field

from novel_harness.config import Settings
from novel_harness.models.base import DomainModel
from novel_harness.providers import build_embedding_provider, build_llm_provider

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("RUN_LIVE_TESTS") != "1",
        reason="set RUN_LIVE_TESTS=1 to spend external provider quota",
    ),
]


class LiveJsonResponse(DomainModel):
    ok: bool
    message: str = Field(min_length=1, max_length=50)


def test_live_qwen_text_embedding_v4() -> None:
    settings = Settings()
    if not settings.qwen_api_key:
        pytest.skip("QWEN_API_KEY is not configured")
    provider = build_embedding_provider(settings)

    vectors = provider.embed_documents(["长篇小说记忆检索", "人物位于长安"])

    assert len(vectors) == 2
    assert all(len(vector) == settings.embedding_dimension for vector in vectors)
    assert vectors[0] != vectors[1]


def test_live_deepseek_v4_flash_json_mode() -> None:
    settings = Settings()
    if not (settings.deepseek_api_key or settings.llm_api_key):
        pytest.skip("DEEPSEEK_API_KEY is not configured")
    provider = build_llm_provider(settings)

    result = provider.generate(
        ('Return one JSON object only. It must have exactly: {"ok": true, "message": "ready"}.'),
        response_model=LiveJsonResponse,
        temperature=0,
        max_tokens=80,
    )

    assert isinstance(result, LiveJsonResponse)
    assert result.ok is True
