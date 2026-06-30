import httpx
import pytest

from novel_harness.api import create_app
from novel_harness.models import (
    ContinuityIssue,
    Document,
    DocumentChunk,
    FactRisk,
    GenerationResult,
    MemoryConflict,
    ResearchNote,
)
from novel_harness.providers.vectorstore import VectorRecord
from novel_harness.storage.repositories import Repositories


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


@pytest.mark.asyncio
async def test_api_deletes_project_and_external_artifacts(runtime) -> None:
    transport = httpx.ASGITransport(app=create_app(runtime=runtime))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/projects",
            json={"name": "待删除", "genre": "历史", "sub_genre": "西汉"},
        )
        project_id = created.json()["id"]

        object_keys = {
            f"projects/{project_id}/drafts/chapter.md",
            f"projects/{project_id}/source/raw.txt",
            f"projects/{project_id}/source/parsed.txt",
            f"projects/{project_id}/chunks/0.txt",
            f"projects/{project_id}/research/source.txt",
        }
        for key in object_keys:
            runtime.object_store.put_bytes(key, b"content")
        runtime.vector_store.upsert(
            [
                VectorRecord(
                    id="document:test-delete",
                    project_id=project_id,
                    source_id="document-test",
                    source_type="document",
                    chunk_ordinal=0,
                    content_hash="hash",
                    embedding=[0.0] * runtime.embedding_provider.dimension,
                )
            ]
        )

        with runtime.session_factory() as session:
            repositories = Repositories(session)
            draft = GenerationResult(
                project_id=project_id,
                body="",
                bible_version=1,
                object_key=f"projects/{project_id}/drafts/chapter.md",
            )
            repositories.generations.add(draft)
            document = Document(
                project_id=project_id,
                filename="raw.txt",
                mime_type="text/plain",
                size_bytes=7,
                content_hash="document-hash",
                object_key=f"projects/{project_id}/source/raw.txt",
                parsed_object_key=f"projects/{project_id}/source/parsed.txt",
                status="ready",
            )
            repositories.documents.add(document)
            repositories.document_chunks.add(
                DocumentChunk(
                    project_id=project_id,
                    document_id=document.id,
                    ordinal=0,
                    content_hash="chunk-hash",
                    object_key=f"projects/{project_id}/chunks/0.txt",
                    status="ready",
                )
            )
            repositories.research.add(
                ResearchNote(
                    project_id=project_id,
                    topic="长安",
                    query="长安",
                    source_title="资料",
                    source_url="https://example.test/source",
                    source_object_key=f"projects/{project_id}/research/source.txt",
                )
            )
            session.commit()

        archived = await client.patch(
            f"/projects/{project_id}",
            json={"status": "archived"},
        )
        assert archived.status_code == 200

        deleted = await client.delete(f"/projects/{project_id}")
        assert deleted.status_code == 200, deleted.text
        assert deleted.json() == {"deleted": True}
        assert (await client.get(f"/projects/{project_id}")).status_code == 404
        assert all(not runtime.object_store.exists(key) for key in object_keys)
        assert runtime.vector_store.records == {}


@pytest.mark.asyncio
async def test_api_quality_review_queue_and_issue_revision(runtime) -> None:
    transport = httpx.ASGITransport(app=create_app(runtime=runtime))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        project_response = await client.post(
            "/projects",
            json={"name": "长安旧梦", "genre": "历史"},
        )
        project_id = project_response.json()["id"]

        object_key = f"projects/{project_id}/drafts/source.md"
        runtime.object_store.put_bytes(
            object_key,
            "林川进入长安，却突然说自己仍在洛阳。".encode(),
            content_type="text/markdown; charset=utf-8",
        )
        with runtime.session_factory() as session:
            repositories = Repositories(session)
            draft = GenerationResult(
                project_id=project_id,
                body="林川进入长安，却突然说自己仍在洛阳。",
                object_key=object_key,
                creative_notes="待审校草稿",
            )
            repositories.generations.add(draft)
            issue = ContinuityIssue(
                project_id=project_id,
                draft_id=draft.id,
                category="timeline",
                severity="error",
                description="人物位置与上一章冲突",
                evidence="上一章林川已入长安",
                suggestion="统一为长安",
            )
            repositories.continuity_issues.add(issue)
            repositories.fact_risks.add(
                FactRisk(
                    project_id=project_id,
                    draft_id=draft.id,
                    claim="长安城门制度",
                    assessment="不确定",
                    risk_level="unknown",
                    reason="缺少资料来源",
                    suggestion="补充史料依据",
                )
            )
            repositories.memory_conflicts.add(
                MemoryConflict(
                    project_id=project_id,
                    severity="soft",
                    category="location",
                    query="林川目前位于洛阳",
                    description="长期记忆显示林川位于长安",
                    memory_ids=["memory-1"],
                    suggestion="确认最新位置",
                )
            )
            session.commit()
            issue_id = issue.id

        listed = await client.get(f"/projects/{project_id}/quality/issues")
        assert listed.status_code == 200, listed.text
        payload = listed.json()
        assert payload["summary"]["total"] == 3
        assert payload["summary"]["open"] == 3
        assert {item["issue_type"] for item in payload["issues"]} == {
            "continuity",
            "fact",
            "memory",
        }

        updated = await client.patch(
            f"/quality/issues/{issue_id}",
            json={"status": "resolved", "resolution_note": "已通过修订处理"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["status"] == "resolved"
        assert updated.json()["resolved_at"] is not None

        open_only = await client.get(
            f"/projects/{project_id}/quality/issues",
            params={"issue_status": "open"},
        )
        assert open_only.status_code == 200
        assert open_only.json()["summary"]["total"] == 2

        revised = await client.post(
            f"/quality/issues/{issue_id}/revise",
            json={"instruction": "把人物位置统一为长安，并保留悬念。"},
        )
        assert revised.status_code == 200, revised.text
        revised_draft = revised.json()["draft"]
        assert revised_draft["parent_draft_id"] == draft.id
        assert revised_draft["revision_number"] == 2


@pytest.mark.asyncio
async def test_api_story_bible_versions_and_diff(runtime) -> None:
    transport = httpx.ASGITransport(app=create_app(runtime=runtime))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/projects",
            json={"name": "长安旧梦", "genre": "历史"},
        )
        project_id = created.json()["id"]

        bible = await client.get(f"/projects/{project_id}/bible")
        assert bible.status_code == 200
        assert bible.json()["version"] == 1

        updated = await client.post(
            f"/projects/{project_id}/bible/rules",
            json={"value": "长安城门开闭受时辰约束", "expected_version": 1},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["version"] == 2

        versions = await client.get(f"/projects/{project_id}/bible/versions")
        assert versions.status_code == 200
        assert [item["version"] for item in versions.json()] == [2, 1]
        assert versions.json()[0]["is_current"] is True

        version_one = await client.get(f"/projects/{project_id}/bible/versions/1")
        assert version_one.status_code == 200
        assert version_one.json()["version"] == 1

        diff = await client.get(
            f"/projects/{project_id}/bible/diff",
            params={"from_version": 1, "to_version": 2},
        )
        assert diff.status_code == 200, diff.text
        assert diff.json()["from_version"] == 1
        assert "长安城门开闭受时辰约束" in diff.json()["unified_diff"]
