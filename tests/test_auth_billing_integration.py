from __future__ import annotations

from typing import Any

import httpx
import pytest

from novel_harness.api import create_app
from novel_harness.exceptions import AuthenticationError, InsufficientBalanceError
from novel_harness.integrations import AuthenticatedUser, BillingServiceClient
from novel_harness.providers.llm import LLMResponse, MockLLMProvider
from novel_harness.services import AgentRunService, ProjectService


class FakeAuthClient:
    async def verify(self, token: str) -> AuthenticatedUser:
        if not token.startswith("user-"):
            raise AuthenticationError("认证已失效，请重新登录")
        return AuthenticatedUser(id=int(token.removeprefix("user-")))

    async def health(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None


class FakeBillingClient:
    def __init__(self, *, reject: bool = False) -> None:
        self.reject = reject
        self.checked: list[int] = []
        self.usage: list[dict[str, Any]] = []

    async def ensure_available_balance(self, user_id: int) -> None:
        self.checked.append(user_id)
        if self.reject:
            raise InsufficientBalanceError("余额不足")

    async def record_usage(self, **payload: Any) -> None:
        self.usage.append(payload)


@pytest.mark.asyncio
async def test_api_requires_auth_and_isolates_projects_by_user(runtime) -> None:
    runtime.settings.auth_required = True
    runtime._auth_client = FakeAuthClient()
    transport = httpx.ASGITransport(app=create_app(runtime=runtime))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unauthenticated = await client.get("/projects")
        assert unauthenticated.status_code == 401

        created = await client.post(
            "/projects",
            headers={"Authorization": "Bearer user-11"},
            json={"name": "长安", "genre": "历史"},
        )
        assert created.status_code == 201
        project_id = created.json()["id"]
        assert created.json()["owner_user_id"] == 11

        owner_listing = await client.get(
            "/projects",
            headers={"Authorization": "Bearer user-11"},
        )
        assert [item["id"] for item in owner_listing.json()] == [project_id]

        other_listing = await client.get(
            "/projects",
            headers={"Authorization": "Bearer user-12"},
        )
        assert other_listing.json() == []
        hidden = await client.get(
            f"/projects/{project_id}",
            headers={"Authorization": "Bearer user-12"},
        )
        assert hidden.status_code == 404


@pytest.mark.asyncio
async def test_agent_run_checks_balance_and_reports_usage(session) -> None:
    project = ProjectService(session).create(
        owner_user_id=42,
        name="长安",
        genre="历史",
    )
    provider = MockLLMProvider(
        responses=[
            LLMResponse(
                content="完成",
                model="deepseek-chat",
                prompt_tokens=120,
                completion_tokens=30,
            )
        ]
    )
    billing = FakeBillingClient()
    service = AgentRunService(
        session,
        provider=provider,
        billing_client=billing,  # type: ignore[arg-type]
    )

    async def operation() -> str:
        return provider.generate("测试")

    assert await service.execute(project.id, "scene_writer", operation) == "完成"
    assert billing.checked == [42]
    assert billing.usage == [
        {
            "user_id": 42,
            "model": "deepseek-chat",
            "subsystem": "novel_harness",
            "input_tokens": 120,
            "output_tokens": 30,
        }
    ]


@pytest.mark.asyncio
async def test_agent_run_stops_before_provider_when_balance_is_insufficient(session) -> None:
    project = ProjectService(session).create(
        owner_user_id=7,
        name="长安",
        genre="历史",
    )
    billing = FakeBillingClient(reject=True)
    called = False

    async def operation() -> str:
        nonlocal called
        called = True
        return "不应执行"

    service = AgentRunService(
        session,
        provider=None,
        billing_client=billing,  # type: ignore[arg-type]
    )
    with pytest.raises(InsufficientBalanceError):
        await service.execute(project.id, "scene_writer", operation)
    assert called is False
    assert service.list(project.id) == []


@pytest.mark.asyncio
async def test_billing_client_rejects_zero_balance() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Internal-Api-Key"] == "test-key"
        return httpx.Response(
            200,
            json={"success": True, "balance": 0, "is_negative": False},
        )

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://billing.test",
    )
    client = BillingServiceClient(
        "http://billing.test",
        internal_api_key="test-key",
        timeout_seconds=1,
        client=http_client,
    )
    try:
        with pytest.raises(InsufficientBalanceError):
            await client.ensure_available_balance(42)
    finally:
        await http_client.aclose()
