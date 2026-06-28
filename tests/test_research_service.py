from __future__ import annotations

import pytest

from novel_harness.agents import ResearchAgent
from novel_harness.models import NovelProject
from novel_harness.providers.content import FetchResult
from novel_harness.providers.embedding import DeterministicEmbeddingProvider
from novel_harness.providers.search import MockSearchProvider, SearchResult
from novel_harness.services import ProjectService, ResearchService


class StubFetcher:
    def fetch(self, url: str) -> FetchResult:
        source = (
            "关于汉长安城门形制，考古报告记载部分城门采用一门三道形制，"
            "门道结构与通行等级需要结合遗址层位判断。"
        )
        suffix = "该结论仍需结合具体遗址年代核对。" if "one" in url else "不同遗址的宽度存在差异。"
        text = f"{source}{suffix}"
        return FetchResult(
            requested_url=url,
            final_url=url,
            content=text,
            content_type="text/plain",
            status_code=200,
            title="汉长安城考古资料",
            byte_count=len(text.encode()),
        )


class ChallengeFetcher:
    def fetch(self, url: str) -> FetchResult:
        text = "百度安全验证，请完成滑动验证后继续访问。"
        return FetchResult(
            requested_url=url,
            final_url="https://wappass.baidu.com/static/captcha/",
            content=text,
            content_type="text/html",
            status_code=200,
            title="百度安全验证",
            byte_count=len(text.encode()),
        )


@pytest.mark.asyncio
async def test_research_service_fetches_evidence_and_indexes(
    session, fake_object_store, fake_vector_store
) -> None:
    project: NovelProject = ProjectService(session).create(
        name="长安", genre="历史", sub_genre="西汉"
    )

    def responder(_query):
        return [
            SearchResult(
                title="来源一",
                url="https://one.example/article",
                snippet="汉长安城门摘要",
                source="example",
            ),
            SearchResult(
                title="来源二",
                url="https://two.example/report",
                snippet="汉长安城门摘要",
                source="example",
            ),
        ]

    service = ResearchService(
        session,
        ResearchAgent(MockSearchProvider(responder=responder)),
        content_fetcher=StubFetcher(),
        object_store=fake_object_store,
        vector_store=fake_vector_store,
        embedding_provider=DeterministicEmbeddingProvider(),
        max_fetches=5,
    )

    notes = await service.research(project.id, "汉长安城门形制")

    assert len(notes) == 2
    assert all(note.evidence_snippets for note in notes)
    assert all(note.source_object_key for note in notes)
    assert all(fake_object_store.exists(note.source_object_key or "") for note in notes)
    assert all(note.verification_status == "corroborated" for note in notes)
    assert any(record.source_type == "research" for record in fake_vector_store.records.values())


@pytest.mark.asyncio
async def test_research_service_rejects_access_challenge_pages(
    session, fake_object_store, fake_vector_store
) -> None:
    project = ProjectService(session).create(name="长安", genre="历史")
    search = MockSearchProvider(
        responder=lambda _query: [
            SearchResult(
                title="待验证来源",
                url="https://example.com/article",
                snippet="汉长安城门摘要",
                source="example",
            )
        ]
    )
    service = ResearchService(
        session,
        ResearchAgent(search),
        content_fetcher=ChallengeFetcher(),
        object_store=fake_object_store,
        vector_store=fake_vector_store,
        embedding_provider=DeterministicEmbeddingProvider(),
    )

    notes = await service.research(project.id, "汉长安城门形制")

    assert len(notes) == 1
    assert notes[0].verification_status == "fetch_failed"
    assert notes[0].evidence_snippets == []
    assert notes[0].source_object_key is None
    assert "验证页面" in (notes[0].uncertainty or "")
    assert not fake_object_store.objects
    assert not fake_vector_store.records
