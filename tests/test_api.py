import httpx
import pytest

from novel_harness.api import create_app
from novel_harness.providers.vectorstore import VectorRecord


@pytest.mark.asyncio
async def test_api_mock_end_to_end(runtime) -> None:
    transport = httpx.ASGITransport(app=create_app(runtime=runtime))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        project_response = await client.post(
            "/projects",
            json={"name": "长安旧梦", "genre": "历史", "sub_genre": "西汉"},
        )
        assert project_response.status_code == 201, project_response.text
        project_id = project_response.json()["id"]
        runtime.vector_store.upsert(
            [
                VectorRecord(
                    id="memory:test",
                    project_id=project_id,
                    source_id="memory-test",
                    source_type="memory",
                    chunk_ordinal=0,
                    content_hash="memory-hash",
                    embedding=[0.0] * runtime.embedding_provider.dimension,
                    metadata={
                        "preview": "主角当前位于长安城外。",
                        "kind": "location_state",
                    },
                )
            ]
        )

        style_response = await client.post(
            f"/projects/{project_id}/style/analyze",
            files={
                "files": (
                    "sample.txt",
                    "雨落长街。\n“走吧。”林川说。",
                    "text/plain",
                )
            },
        )
        assert style_response.status_code == 200, style_response.text

        research_response = await client.post(
            f"/projects/{project_id}/research",
            json={"topic": "西汉长安市井生活"},
        )
        assert research_response.status_code == 200, research_response.text
        assert research_response.json()

        plan_response = await client.post(
            f"/projects/{project_id}/plot/plan",
            json={"current": "主角抵达城外", "goal": "进入长安"},
        )
        assert plan_response.status_code == 200, plan_response.text
        assert len(plan_response.json()["next_chapter_options"]) == 3

        write_response = await client.post(
            f"/projects/{project_id}/write",
            json={"goal": "主角第一次进入长安", "current": "主角抵达城外"},
        )
        assert write_response.status_code == 200, write_response.text
        payload = write_response.json()
        assert payload["draft"]["body"]
        assert payload["draft"]["creative_notes"]
        assert payload["draft"]["factual_basis_summary"]
        assert payload["draft"]["retrieval_query"]
        assert payload["draft"]["context_sources"]
        assert any(
            source["source_type"] == "memory" for source in payload["draft"]["context_sources"]
        )


@pytest.mark.asyncio
async def test_api_returns_404_for_unknown_project(runtime) -> None:
    transport = httpx.ASGITransport(app=create_app(runtime=runtime))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/projects/missing/bible")
        assert response.status_code == 404
        assert response.json()["error"] == "not_found"


@pytest.mark.asyncio
async def test_api_creates_and_cancels_workflow(runtime) -> None:
    transport = httpx.ASGITransport(app=create_app(runtime=runtime))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        project_response = await client.post(
            "/projects",
            json={"name": "长安旧梦", "genre": "历史"},
        )
        project_id = project_response.json()["id"]

        created = await client.post(
            f"/projects/{project_id}/workflows",
            json={
                "goal": "进入长安",
                "current": "主角抵达城外",
                "auto_approve": False,
            },
        )
        assert created.status_code == 202, created.text
        run_id = created.json()["run"]["id"]

        fetched = await client.get(f"/workflows/{run_id}")
        assert fetched.status_code == 200
        assert fetched.json()["run"]["status"] == "queued"

        cancelled = await client.post(f"/workflows/{run_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["run"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_api_exposes_empty_memory_state_and_query(runtime) -> None:
    transport = httpx.ASGITransport(app=create_app(runtime=runtime))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        project_response = await client.post(
            "/projects",
            json={"name": "长安旧梦", "genre": "历史"},
        )
        project_id = project_response.json()["id"]

        state = await client.get(f"/projects/{project_id}/memory/state")
        assert state.status_code == 200
        assert state.json()["revision"] == 0

        query = await client.post(
            f"/projects/{project_id}/memory/query",
            json={"query": "主角目前位于哪里", "limit": 5},
        )
        assert query.status_code == 200, query.text
        assert query.json() == {"revision": 0, "hits": [], "conflicts": []}


@pytest.mark.asyncio
async def test_api_updates_archives_and_restores_project(runtime) -> None:
    transport = httpx.ASGITransport(app=create_app(runtime=runtime))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/projects",
            json={"name": "旧名", "genre": "历史"},
        )
        project_id = created.json()["id"]

        updated = await client.patch(
            f"/projects/{project_id}",
            json={"name": "长安旧梦", "tone": "克制"},
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "长安旧梦"
        assert updated.json()["tone"] == "克制"

        archived = await client.patch(
            f"/projects/{project_id}",
            json={"status": "archived"},
        )
        assert archived.status_code == 200
        assert archived.json()["status"] == "archived"
        assert archived.json()["archived_at"] is not None

        assert (await client.get("/projects")).json() == []
        all_projects = await client.get("/projects?include_archived=true")
        assert all_projects.json()[0]["id"] == project_id

        blocked = await client.get(f"/projects/{project_id}/bible")
        assert blocked.status_code == 409
        assert blocked.json()["error"] == "project_archived"
        blocked_update = await client.patch(
            f"/projects/{project_id}",
            json={"name": "不应更新"},
        )
        assert blocked_update.status_code == 409

        restored = await client.patch(
            f"/projects/{project_id}",
            json={"status": "active"},
        )
        assert restored.status_code == 200
        assert restored.json()["archived_at"] is None
        assert (await client.get("/projects")).json()[0]["id"] == project_id
