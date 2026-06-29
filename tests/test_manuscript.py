from __future__ import annotations

import io
import json
import zipfile

import httpx
import pytest
from docx import Document

from novel_harness.api import create_app


@pytest.mark.asyncio
async def test_manuscript_outline_reorder_and_export(runtime) -> None:
    transport = httpx.ASGITransport(app=create_app(runtime=runtime))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        project = (
            await client.post(
                "/projects",
                json={
                    "name": "长安旧梦",
                    "genre": "历史",
                    "premise": "一名小吏卷入宫廷密案。",
                },
            )
        ).json()
        project_id = project["id"]

        initial = await client.get(f"/projects/{project_id}/manuscript")
        assert initial.status_code == 200
        first_volume = initial.json()["volumes"][0]
        assert first_volume["title"] == "第一卷"

        second_volume_response = await client.post(
            f"/projects/{project_id}/volumes",
            json={"title": "风雨入京"},
        )
        assert second_volume_response.status_code == 201
        second_volume = second_volume_response.json()

        written = await client.post(
            f"/projects/{project_id}/write",
            json={"goal": "主角通过城门", "current": "主角抵达城外"},
        )
        accepted_draft = written.json()["draft"]

        accepted_chapter = await client.post(
            f"/projects/{project_id}/chapters",
            json={
                "volume_id": second_volume["id"],
                "title": "第一章 横门夜雨",
                "draft_id": accepted_draft["id"],
            },
        )
        assert accepted_chapter.status_code == 201, accepted_chapter.text
        assert accepted_chapter.json()["status"] == "drafting"

        accepted = await client.post(f"/drafts/{accepted_draft['id']}/accept")
        assert accepted.status_code == 200
        refreshed = await client.get(f"/projects/{project_id}/manuscript")
        linked = next(
            item
            for item in refreshed.json()["chapters"]
            if item["id"] == accepted_chapter.json()["id"]
        )
        assert linked["status"] == "accepted"
        assert linked["accepted_draft_id"] == accepted_draft["id"]

        duplicate = await client.post(
            f"/projects/{project_id}/chapters",
            json={
                "volume_id": first_volume["id"],
                "title": "重复关联",
                "draft_id": accepted_draft["id"],
            },
        )
        assert duplicate.status_code == 422
        assert "已经关联" in duplicate.json()["message"]

        planned_one = await client.post(
            f"/projects/{project_id}/chapters",
            json={"volume_id": first_volume["id"], "title": "待写章节一"},
        )
        planned_two = await client.post(
            f"/projects/{project_id}/chapters",
            json={"volume_id": first_volume["id"], "title": "待写章节二"},
        )
        assert planned_one.json()["status"] == "planned"

        reordered_chapters = await client.post(
            f"/projects/{project_id}/volumes/{first_volume['id']}/chapters/reorder",
            json={"ordered_ids": [planned_two.json()["id"], planned_one.json()["id"]]},
        )
        assert reordered_chapters.status_code == 200
        assert [item["title"] for item in reordered_chapters.json()] == [
            "待写章节二",
            "待写章节一",
        ]

        reordered_volumes = await client.post(
            f"/projects/{project_id}/volumes/reorder",
            json={"ordered_ids": [second_volume["id"], first_volume["id"]]},
        )
        assert reordered_volumes.status_code == 200
        assert [item["title"] for item in reordered_volumes.json()] == [
            "风雨入京",
            "第一卷",
        ]

        markdown = await client.get(f"/projects/{project_id}/export?format=markdown")
        assert markdown.status_code == 200, markdown.text
        assert "# 长安旧梦" in markdown.text
        assert "## 风雨入京" in markdown.text
        assert "### 第一章 横门夜雨" in markdown.text
        assert "待写章节一" not in markdown.text

        package = await client.get(f"/projects/{project_id}/export?format=zip")
        assert package.status_code == 200
        with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
            names = archive.namelist()
            assert "manuscript.md" in names
            assert "metadata.json" in names
            assert any(name.endswith("001-第一章 横门夜雨.md") for name in names)
            metadata = json.loads(archive.read("metadata.json"))
            assert metadata["exported_chapters"] == 1

        completed = await client.patch(
            f"/chapters/{accepted_chapter.json()['id']}",
            json={"status": "completed"},
        )
        assert completed.status_code == 200
        assert completed.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_chapter_driven_writing_manual_revision_and_docx_export(runtime) -> None:
    transport = httpx.ASGITransport(app=create_app(runtime=runtime))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        project_id = (
            await client.post(
                "/projects",
                json={"name": "长安手稿", "genre": "历史"},
            )
        ).json()["id"]
        volume = (await client.get(f"/projects/{project_id}/manuscript")).json()["volumes"][0]
        chapter = (
            await client.post(
                f"/projects/{project_id}/chapters",
                json={
                    "volume_id": volume["id"],
                    "title": "第一章 城门",
                    "summary": "主角通过城门",
                },
            )
        ).json()

        written = await client.post(
            f"/projects/{project_id}/write",
            json={
                "goal": "主角通过城门",
                "current": "主角抵达城外",
                "chapter_id": chapter["id"],
            },
        )
        assert written.status_code == 200, written.text
        first = written.json()["draft"]
        assert first["chapter_id"] == chapter["id"]

        outline = (await client.get(f"/projects/{project_id}/manuscript")).json()
        linked = outline["chapters"][0]
        assert linked["draft_id"] == first["id"]
        assert linked["accepted_draft_id"] is None
        assert linked["status"] == "drafting"

        assert (await client.post(f"/drafts/{first['id']}/accept")).status_code == 200
        linked = (await client.get(f"/projects/{project_id}/manuscript")).json()["chapters"][0]
        assert linked["accepted_draft_id"] == first["id"]
        assert linked["status"] == "accepted"

        manual_body = "作者手工改写后的第一段。\n\n这是第二段。"
        manual = await client.post(
            f"/drafts/{first['id']}/manual-revision",
            json={
                "body": manual_body,
                "note": "调整叙述节奏",
                "run_checks": False,
            },
        )
        assert manual.status_code == 200, manual.text
        second = manual.json()["draft"]
        assert second["parent_draft_id"] == first["id"]
        assert second["chapter_id"] == chapter["id"]
        assert second["revision_number"] == 2

        linked = (await client.get(f"/projects/{project_id}/manuscript")).json()["chapters"][0]
        assert linked["draft_id"] == second["id"]
        assert linked["accepted_draft_id"] == first["id"]
        assert linked["status"] == "drafting"
        old_export = await client.get(f"/projects/{project_id}/export")
        assert manual_body not in old_export.text

        assert (await client.post(f"/drafts/{second['id']}/accept")).status_code == 200
        preview = await client.get(f"/projects/{project_id}/export/preview")
        assert preview.status_code == 200
        assert preview.json()["exportable_chapter_count"] == 1
        assert preview.json()["total_characters"] == len("作者手工改写后的第一段。这是第二段。")
        assert preview.json()["total_paragraphs"] == 2

        docx = await client.get(f"/projects/{project_id}/export?format=docx")
        assert docx.status_code == 200
        document = Document(io.BytesIO(docx.content))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        assert "第一章 城门" in text
        assert "作者手工改写后的第一段。" in text

        third = (
            await client.post(
                f"/drafts/{second['id']}/manual-revision",
                json={"body": "这一版最终被作者放弃。", "note": "尝试另一种写法"},
            )
        ).json()["draft"]
        rejected = await client.post(
            f"/drafts/{third['id']}/reject",
            json={"reason": "保留上一版"},
        )
        assert rejected.status_code == 200
        linked = (await client.get(f"/projects/{project_id}/manuscript")).json()["chapters"][0]
        assert linked["draft_id"] == second["id"]
        assert linked["accepted_draft_id"] == second["id"]
        assert linked["status"] == "accepted"


@pytest.mark.asyncio
async def test_manuscript_rejects_export_without_accepted_chapters(runtime) -> None:
    transport = httpx.ASGITransport(app=create_app(runtime=runtime))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        project_id = (
            await client.post(
                "/projects",
                json={"name": "空白作品", "genre": "悬疑"},
            )
        ).json()["id"]
        response = await client.get(f"/projects/{project_id}/export")
        assert response.status_code == 422
        assert response.json()["error"] == "invalid_request"
