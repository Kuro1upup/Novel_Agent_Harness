import httpx
from pydantic import BaseModel

from novel_harness.providers.llm import MockLLMProvider
from novel_harness.providers.search import SearXNGSearchProvider


class StructuredAnswer(BaseModel):
    title: str
    items: list[str]


def test_mock_llm_generates_schema_valid_data() -> None:
    result = MockLLMProvider().generate_structured("return JSON", StructuredAnswer)
    assert isinstance(result, StructuredAnswer)


def test_searxng_normalizes_json_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["format"] == "json"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "汉代长安",
                        "url": "https://example.test/changan",
                        "content": "资料摘要",
                        "engine": "example",
                        "score": 0.8,
                    }
                ]
            },
        )

    provider = SearXNGSearchProvider(
        base_url="https://search.example.test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    results = provider.search("长安", max_results=3)
    assert len(results) == 1
    assert results[0].title == "汉代长安"
    assert results[0].source == "example"
