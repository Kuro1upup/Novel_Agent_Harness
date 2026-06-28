import json

import httpx
from pydantic import BaseModel

from novel_harness.providers.llm import OpenAICompatibleLLMProvider


class Answer(BaseModel):
    value: str


def test_deepseek_json_mode_uses_official_compatible_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.deepseek.com/chat/completions"
        assert request.headers["authorization"] == "Bearer secret"
        payload = json.loads(request.content)
        assert payload["model"] == "deepseek-v4-flash"
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={
                "model": "deepseek-v4-flash",
                "choices": [
                    {
                        "message": {"content": '{"value":"ok","metadata":{"provider":"deepseek"}}'},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    provider = OpenAICompatibleLLMProvider(
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        api_key="secret",
        supports_json_schema=False,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert provider.generate_structured("Return JSON.", Answer) == Answer(value="ok")
