from __future__ import annotations

import hashlib
import json
import tarfile
from pathlib import Path

import pytest

from novel_harness.config import Settings
from novel_harness.models import AgentRun
from novel_harness.providers.llm import LLMResponse, MockLLMProvider
from novel_harness.services import AgentRunService, OpsService, ProjectService


@pytest.mark.asyncio
async def test_agent_run_records_usage_cost_and_prompt_version(session) -> None:
    project = ProjectService(session).create(name="长安", genre="历史")
    provider = MockLLMProvider(
        responses=[
            LLMResponse(
                content="完成",
                model="mock-priced",
                prompt_tokens=120,
                completion_tokens=30,
            )
        ]
    )
    service = AgentRunService(
        session,
        provider=provider,
        input_cost_per_million=2.0,
        output_cost_per_million=8.0,
    )

    async def operation() -> str:
        return provider.generate("不记录这个提示词")

    assert (
        await service.execute(
            project.id,
            "scene_writer",
            operation,
            input_summary="goal_chars=8",
        )
        == "完成"
    )
    run: AgentRun = service.list(project.id)[0]
    assert run.status == "succeeded"
    assert run.model == "mock-priced"
    assert run.prompt_tokens == 120
    assert run.completion_tokens == 30
    assert run.estimated_cost == pytest.approx(0.00048)
    assert len(run.prompt_version) == 12
    assert run.input_summary == "goal_chars=8"


@pytest.mark.asyncio
async def test_agent_run_records_failure_without_prompt_content(session) -> None:
    project = ProjectService(session).create(name="长安", genre="历史")
    service = AgentRunService(session, provider=None)

    async def operation() -> str:
        raise RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await service.execute(
            project.id,
            "scene_writer",
            operation,
            input_summary="draft_chars=1200",
        )

    run = service.list(project.id)[0]
    assert run.status == "failed"
    assert run.error_type == "RuntimeError"
    assert run.error_message == "provider unavailable"
    assert run.input_summary == "draft_chars=1200"


def test_backup_archive_verification(tmp_path: Path) -> None:
    root = tmp_path / "content"
    root.mkdir()
    database = root / "database.sql"
    database.write_text("SELECT 1;\n", encoding="utf-8")
    digest = hashlib.sha256(database.read_bytes()).hexdigest()
    manifest = {
        "format_version": 1,
        "created_at": "2026-06-29T00:00:00+00:00",
        "files": [{"path": "database.sql", "sha256": digest}],
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    archive = tmp_path / "backup.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(root / "database.sql", arcname="database.sql")
        bundle.add(root / "manifest.json", arcname="manifest.json")

    result = OpsService(Settings()).verify_backup(archive)
    assert result["valid"] is True
    assert result["files"] == 1


def test_backup_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.tar.gz"
    payload = tmp_path / "payload"
    payload.write_text("bad", encoding="utf-8")
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(payload, arcname="../escape")

    with pytest.raises(ValueError, match="unsafe path"):
        OpsService(Settings()).verify_backup(archive)
