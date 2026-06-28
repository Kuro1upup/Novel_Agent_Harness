from __future__ import annotations

import httpx
import pytest

from novel_harness.api import create_app


@pytest.mark.asyncio
async def test_creative_agents_apply_only_when_author_requests(runtime) -> None:
    transport = httpx.ASGITransport(app=create_app(runtime=runtime))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        project = (
            await client.post(
                "/projects",
                json={
                    "name": "长安旧梦",
                    "genre": "历史",
                    "premise": "一名小吏卷入宫廷密案",
                },
            )
        ).json()
        project_id = project["id"]

        proposed = await client.post(
            f"/projects/{project_id}/agents/character",
            json={
                "name": "林川",
                "role": "主角",
                "brief": "谨慎的小吏",
                "apply": False,
            },
        )
        assert proposed.status_code == 200, proposed.text
        assert proposed.json()["bible"] is None

        applied = await client.post(
            f"/projects/{project_id}/agents/character",
            json={
                "name": "林川",
                "role": "主角",
                "brief": "谨慎的小吏",
                "apply": True,
            },
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["bible"]["characters"][0]["name"] == "林川"

        world = await client.post(
            f"/projects/{project_id}/agents/worldbuilding",
            json={"goal": "建立长安权力结构", "apply": True},
        )
        assert world.status_code == 200, world.text
        assert world.json()["bible"]["rules"]

        foreshadowing = await client.post(
            f"/projects/{project_id}/agents/foreshadowing",
            json={"scene_goal": "主角进入长安", "max_actions": 3, "apply": True},
        )
        assert foreshadowing.status_code == 200, foreshadowing.text
        assert foreshadowing.json()["bible"]["foreshadowing_items"]

        runs = await client.get(f"/projects/{project_id}/agent-runs")
        assert runs.status_code == 200
        names = [item["agent_name"] for item in runs.json()]
        assert names == [
            "character_agent",
            "character_agent",
            "worldbuilding_agent",
            "foreshadowing_agent",
        ]


@pytest.mark.asyncio
async def test_plot_selection_and_draft_revision_lifecycle(runtime) -> None:
    transport = httpx.ASGITransport(app=create_app(runtime=runtime))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        project_id = (
            await client.post(
                "/projects",
                json={"name": "长安旧梦", "genre": "历史"},
            )
        ).json()["id"]

        plan_response = await client.post(
            f"/projects/{project_id}/plot/plan",
            json={"current": "主角抵达城外", "goal": "通过城门"},
        )
        assert plan_response.status_code == 200, plan_response.text
        plan = plan_response.json()
        option = plan["next_chapter_options"][1]

        selected = await client.post(
            f"/projects/{project_id}/plot/plans/{plan['id']}/select",
            json={"option_id": option["id"]},
        )
        assert selected.status_code == 200
        assert selected.json()["selected_option_id"] == option["id"]

        written = await client.post(
            f"/projects/{project_id}/write",
            json={
                "goal": "通过城门",
                "current": "主角抵达城外",
                "plot_plan_id": plan["id"],
                "selected_option_id": option["id"],
            },
        )
        assert written.status_code == 200, written.text
        first = written.json()["draft"]
        assert first["plot_plan_id"] == plan["id"]
        assert first["selected_option_id"] == option["id"]
        assert first["revision_number"] == 1

        listing = await client.get(f"/projects/{project_id}/drafts")
        assert listing.status_code == 200
        assert listing.json()[0]["body"] == ""

        fetched = await client.get(f"/drafts/{first['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["body"]

        revised = await client.post(
            f"/drafts/{first['id']}/revise",
            json={"instruction": "减少巧合，强化主角主动观察"},
        )
        assert revised.status_code == 200, revised.text
        second = revised.json()["draft"]
        assert second["parent_draft_id"] == first["id"]
        assert second["revision_number"] == 2
        assert second["revision_instruction"] == "减少巧合，强化主角主动观察"

        diff = await client.get(f"/drafts/{first['id']}/diff/{second['id']}")
        assert diff.status_code == 200
        assert "unified_diff" in diff.json()

        rejected = await client.post(
            f"/drafts/{second['id']}/reject",
            json={"reason": "节奏仍然过慢"},
        )
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_story_bible_entry_endpoints_and_foreshadowing_resolution(runtime) -> None:
    transport = httpx.ASGITransport(app=create_app(runtime=runtime))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        project_id = (
            await client.post("/projects", json={"name": "长安", "genre": "历史"})
        ).json()["id"]
        bible = (await client.get(f"/projects/{project_id}/bible")).json()

        rule = await client.post(
            f"/projects/{project_id}/bible/rules",
            json={"value": "城门夜间关闭", "expected_version": bible["version"]},
        )
        assert rule.status_code == 200
        bible = rule.json()

        faction = await client.post(
            f"/projects/{project_id}/bible/factions",
            json={"value": {"name": "廷尉府"}, "expected_version": bible["version"]},
        )
        assert faction.status_code == 200
        bible = faction.json()

        location = await client.post(
            f"/projects/{project_id}/bible/locations",
            json={"value": {"name": "横门"}, "expected_version": bible["version"]},
        )
        assert location.status_code == 200
        bible = location.json()

        timeline = await client.post(
            f"/projects/{project_id}/bible/timeline",
            json={
                "sequence": 1,
                "summary": "主角抵达横门",
                "expected_version": bible["version"],
            },
        )
        assert timeline.status_code == 200
        bible = timeline.json()

        planted = await client.post(
            f"/projects/{project_id}/bible/foreshadowing",
            json={
                "description": "残缺铜符",
                "expected_version": bible["version"],
            },
        )
        item = planted.json()["foreshadowing_items"][0]
        resolved = await client.post(
            f"/projects/{project_id}/bible/foreshadowing/{item['id']}/resolve",
            json={
                "resolution": "铜符证明密使身份",
                "expected_version": planted.json()["version"],
            },
        )
        assert resolved.status_code == 200
        assert resolved.json()["foreshadowing_items"][0]["status"] == "resolved"
        assert resolved.json()["resolved_threads"][-1] == "铜符证明密使身份"
