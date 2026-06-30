from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from novel_harness.api import create_app
from novel_harness.exceptions import AuthenticationError, InsufficientBalanceError
from novel_harness.integrations import AuthenticatedUser, AuthServiceClient, BillingServiceClient
from novel_harness.models import GenerationResult
from novel_harness.providers.llm import LLMResponse, MockLLMProvider
from novel_harness.security import bind_user, reset_user
from novel_harness.services import AgentRunService, ProjectService, WorkflowService
from novel_harness.storage import Repositories, session_scope


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
async def test_auth_client_bootstraps_local_user_with_internal_key() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/auth/internal/bootstrap"
        assert request.headers["X-Internal-Api-Key"] == "test-key"
        payload = json.loads(request.content)
        assert payload["email"] == "author@local.test"
        assert payload["reset_password"] is False
        return httpx.Response(
            200,
            json={
                "success": True,
                "created": True,
                "user": {
                    "id": 42,
                    "email": "author@local.test",
                    "nickname": "本地作者",
                },
            },
        )

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://auth.test",
    )
    client = AuthServiceClient(
        "http://auth.test",
        internal_api_key="test-key",
        timeout_seconds=1,
        client=http_client,
    )
    try:
        result = await client.bootstrap_local_user(
            email="author@local.test",
            password="local-password",
            nickname="本地作者",
        )
        assert result.created is True
        assert result.user.id == 42
        assert result.user.email == "author@local.test"
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_auth_client_requires_internal_key_for_local_bootstrap() -> None:
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
        base_url="http://auth.test",
    )
    client = AuthServiceClient(
        "http://auth.test",
        internal_api_key="",
        timeout_seconds=1,
        client=http_client,
    )
    try:
        with pytest.raises(AuthenticationError, match="AUTH_INTERNAL_API_KEY"):
            await client.bootstrap_local_user(
                email="author@local.test",
                password="local-password",
                nickname="本地作者",
            )
    finally:
        await http_client.aclose()


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
        denied_delete = await client.delete(
            f"/projects/{project_id}",
            headers={"Authorization": "Bearer user-12"},
        )
        assert denied_delete.status_code == 404
        still_owned = await client.get(
            f"/projects/{project_id}",
            headers={"Authorization": "Bearer user-11"},
        )
        assert still_owned.status_code == 200


@pytest.mark.asyncio
async def test_api_development_mode_lists_legacy_projects(runtime) -> None:
    runtime.settings.auth_required = False
    with session_scope(runtime.session_factory) as db_session:
        legacy = ProjectService(db_session).create(name="旧项目", genre="历史")

    transport = httpx.ASGITransport(app=create_app(runtime=runtime))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/projects")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [legacy.id]
    assert response.json()[0]["owner_user_id"] == 0


@pytest.mark.asyncio
async def test_api_isolates_drafts_and_workflows_by_user(runtime) -> None:
    runtime.settings.auth_required = True
    runtime._auth_client = FakeAuthClient()
    transport = httpx.ASGITransport(app=create_app(runtime=runtime))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/projects",
            headers={"Authorization": "Bearer user-11"},
            json={"name": "长安", "genre": "历史"},
        )
        project_id = created.json()["id"]

        with session_scope(runtime.session_factory) as db_session:
            repositories = Repositories(db_session)
            draft = repositories.generations.add(
                GenerationResult(project_id=project_id, body="", bible_version=1)
            )
            workflow_id = (
                WorkflowService(db_session)
                .create_chapter_workflow(
                    project_id,
                    goal="进入长安",
                )
                .run.id
            )

        owner_draft = await client.get(
            f"/drafts/{draft.id}",
            headers={"Authorization": "Bearer user-11"},
        )
        other_draft = await client.get(
            f"/drafts/{draft.id}",
            headers={"Authorization": "Bearer user-12"},
        )
        owner_workflow = await client.get(
            f"/workflows/{workflow_id}",
            headers={"Authorization": "Bearer user-11"},
        )
        other_workflow = await client.get(
            f"/workflows/{workflow_id}",
            headers={"Authorization": "Bearer user-12"},
        )

    assert owner_draft.status_code == 200
    assert other_draft.status_code == 404
    assert owner_workflow.status_code == 200
    assert other_workflow.status_code == 404


def test_repositories_scope_secondary_queries_to_current_user(session) -> None:
    project_11 = ProjectService(session).create(
        owner_user_id=11,
        name="长安",
        genre="历史",
    )
    project_12 = ProjectService(session).create(
        owner_user_id=12,
        name="洛阳",
        genre="历史",
    )
    repositories = Repositories(session)
    draft_11 = repositories.generations.add(
        GenerationResult(project_id=project_11.id, body="", bible_version=1)
    )
    repositories.generations.add(
        GenerationResult(project_id=project_12.id, body="", bible_version=1)
    )
    run_11 = (
        WorkflowService(session)
        .create_chapter_workflow(
            project_11.id,
            goal="进入长安",
        )
        .run
    )
    run_12 = (
        WorkflowService(session)
        .create_chapter_workflow(
            project_12.id,
            goal="进入洛阳",
        )
        .run
    )

    token = bind_user(11)
    try:
        assert [item.id for item in repositories.generations.list_by_status(project_11.id)] == [
            draft_11.id
        ]
        assert repositories.generations.list_by_status(project_12.id) == []
        assert [item.id for item in repositories.workflow_runs.list_for_project(project_11.id)] == [
            run_11.id
        ]
        assert repositories.workflow_runs.list_for_project(project_12.id) == []
        assert repositories.workflow_steps.list_for_run(run_11.id)
        assert repositories.workflow_steps.list_for_run(run_12.id) == []
    finally:
        reset_user(token)


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
    assert len(billing.usage) == 1
    usage = dict(billing.usage[0])
    assert str(usage.pop("event_id")).startswith("agent-run:")
    assert usage == {
        "user_id": 42,
        "model": "deepseek-chat",
        "subsystem": "novel_harness",
        "input_tokens": 120,
        "output_tokens": 30,
    }


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


@pytest.mark.asyncio
async def test_billing_client_reports_usage_with_event_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/billing/internal/usage"
        assert request.headers["X-Internal-Api-Key"] == "test-key"
        payload = json.loads(request.content)
        assert payload["event_id"] == "agent-run:test-trace"
        assert payload["user_id"] == 42
        assert payload["input_tokens"] == 12
        assert payload["cache_miss_tokens"] == 12
        return httpx.Response(200, json={"success": True, "id": 1})

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
        await client.record_usage(
            event_id="agent-run:test-trace",
            user_id=42,
            model="deepseek",
            subsystem="novel_harness",
            input_tokens=12,
            output_tokens=8,
        )
    finally:
        await http_client.aclose()
