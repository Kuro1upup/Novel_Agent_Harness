"""Typer command line interface."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import typer
from alembic import command
from alembic.config import Config
from fastapi.encoders import jsonable_encoder

from novel_harness.config import get_settings
from novel_harness.core.workflow import WorkflowWorker
from novel_harness.logging_config import configure_logging
from novel_harness.models import CharacterProfile
from novel_harness.runtime import Runtime
from novel_harness.services import ProjectService, StoryBibleService, WorkflowService
from novel_harness.storage import (
    check_database,
    provision_mysql,
    session_scope,
)

app = typer.Typer(
    name="novel-harness",
    help="Provider-neutral long-form fiction writing agent harness.",
    no_args_is_help=True,
)
bible_app = typer.Typer(help="Inspect and update Story Bible canon.")
draft_app = typer.Typer(help="Manage generated drafts.")
infra_app = typer.Typer(help="Check backing services.")
db_app = typer.Typer(help="Initialize and migrate MySQL.")
vector_app = typer.Typer(help="Maintain Milvus indexes.")
workflow_app = typer.Typer(help="Create and control durable chapter workflows.")
memory_app = typer.Typer(help="Query and rebuild accepted-chapter memory.")
app.add_typer(bible_app, name="bible")
app.add_typer(draft_app, name="draft")
app.add_typer(infra_app, name="infra")
app.add_typer(db_app, name="db")
app.add_typer(vector_app, name="vector")
app.add_typer(workflow_app, name="workflow")
app.add_typer(memory_app, name="memory")

_runtime: Runtime | None = None


def runtime() -> Runtime:
    global _runtime
    if _runtime is None:
        settings = get_settings()
        configure_logging(settings.log_level)
        _runtime = Runtime(settings)
    return _runtime


def output(value: Any) -> None:
    if hasattr(value, "model_dump_json"):
        typer.echo(value.model_dump_json(indent=2))
    else:
        typer.echo(
            json.dumps(
                jsonable_encoder(value),
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )


@app.command("init")
def init_project(
    project_name: str = typer.Argument(..., help="Project name."),
    genre: str = typer.Option(..., "--genre", help="Primary genre."),
    sub_genre: str | None = typer.Option(None, "--sub-genre"),
    premise: str = typer.Option("", "--premise"),
    target_audience: str = typer.Option("", "--target-audience"),
    tone: str = typer.Option("", "--tone"),
) -> None:
    with session_scope(runtime().session_factory) as session:
        project = ProjectService(session).create(
            name=project_name,
            genre=genre,
            sub_genre=sub_genre,
            premise=premise,
            target_audience=target_audience,
            tone=tone,
        )
        output(project)


@app.command("ingest-style")
def ingest_style(
    project_id: str,
    path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
) -> None:
    async def run() -> Any:
        with session_scope(runtime().session_factory) as session:
            document, text = runtime().document_service(session).ingest_path(project_id, path)
            return (
                await runtime()
                .generation_service(session)
                .analyze_style(project_id, text, source_document_ids=[document.id])
            )

    output(asyncio.run(run()))


@app.command("research")
def research(project_id: str, topic: str) -> None:
    async def run() -> Any:
        with session_scope(runtime().session_factory) as session:
            return await runtime().research_service(session).research(project_id, topic)

    output(asyncio.run(run()))


@bible_app.command("show")
def bible_show(project_id: str) -> None:
    with session_scope(runtime().session_factory) as session:
        output(StoryBibleService(session).get(project_id))


@bible_app.command("add-character")
def bible_add_character(
    project_id: str,
    character_json: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
) -> None:
    payload = json.loads(character_json.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise typer.BadParameter("character JSON must be an object")
    payload.pop("project_id", None)
    with session_scope(runtime().session_factory) as session:
        character = CharacterProfile(project_id=project_id, **payload)
        output(StoryBibleService(session).add_character(project_id, character))


@bible_app.command("add-foreshadowing")
def bible_add_foreshadowing(project_id: str, description: str) -> None:
    with session_scope(runtime().session_factory) as session:
        output(StoryBibleService(session).add_foreshadowing(project_id, description))


@app.command("plan")
def plan(
    project_id: str,
    current: str = typer.Option(..., "--current"),
    goal: str = typer.Option("推进下一阶段剧情", "--goal"),
) -> None:
    async def run() -> Any:
        with session_scope(runtime().session_factory) as session:
            return await runtime().generation_service(session).plan(project_id, current, goal)

    output(asyncio.run(run()))


@app.command("write")
def write(
    project_id: str,
    goal: str = typer.Option(..., "--goal"),
    current: str = typer.Option("", "--current"),
) -> None:
    async def run() -> dict[str, Any]:
        with session_scope(runtime().session_factory) as session:
            draft, issues, risks, originality, patch_id = (
                await runtime()
                .generation_service(session)
                .write(project_id, goal, current_summary=current)
            )
            return {
                "draft": draft.model_dump(mode="json"),
                "continuity_issues": [issue.model_dump(mode="json") for issue in issues],
                "fact_risks": [risk.model_dump(mode="json") for risk in risks],
                "originality": asdict(originality),
                "canon_patch_id": patch_id,
            }

    output(asyncio.run(run()))


@app.command("check")
def check(
    project_id: str,
    path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
) -> None:
    async def run() -> dict[str, Any]:
        with session_scope(runtime().session_factory) as session:
            draft = path.read_text(encoding="utf-8")
            issues, risks = await runtime().generation_service(session).check(project_id, draft)
            return {
                "continuity_issues": [issue.model_dump(mode="json") for issue in issues],
                "fact_risks": [risk.model_dump(mode="json") for risk in risks],
            }

    output(asyncio.run(run()))


@draft_app.command("accept")
def draft_accept(draft_id: str) -> None:
    with session_scope(runtime().session_factory) as session:
        repositories = StoryBibleService(session).repositories
        matches = [
            patch
            for project in repositories.projects.list()
            for patch in repositories.canon_patches.list(project.id)
            if patch.draft_id == draft_id
        ]
        if not matches:
            raise typer.BadParameter(f"no pending canon patch for draft {draft_id}")
        output(StoryBibleService(session).accept_patch(matches[0].id))


@workflow_app.command("start")
def workflow_start(
    project_id: str,
    goal: str = typer.Option(..., "--goal"),
    current: str = typer.Option("", "--current"),
    research_topic: str | None = typer.Option(None, "--research-topic"),
    auto_approve: bool = typer.Option(False, "--auto-approve"),
    max_attempts: int = typer.Option(3, "--max-attempts", min=1, max=20),
    idempotency_key: str | None = typer.Option(None, "--idempotency-key"),
) -> None:
    with session_scope(runtime().session_factory) as session:
        detail = WorkflowService(
            session,
            cache_provider=runtime().cache_provider,
        ).create_chapter_workflow(
            project_id,
            goal=goal,
            current=current,
            research_topic=research_topic,
            auto_approve=auto_approve,
            max_attempts=max_attempts,
            idempotency_key=idempotency_key,
        )
        output(detail)


@workflow_app.command("show")
def workflow_show(run_id: str) -> None:
    with session_scope(runtime().session_factory) as session:
        output(WorkflowService(session).detail(run_id))


@workflow_app.command("approve")
def workflow_approve(
    run_id: str,
    step_name: str,
    decision: str = typer.Option("approve", "--decision"),
    actor: str = typer.Option("author", "--actor"),
    note: str = typer.Option("", "--note"),
) -> None:
    with session_scope(runtime().session_factory) as session:
        output(
            WorkflowService(
                session,
                cache_provider=runtime().cache_provider,
            ).decide_approval(
                run_id,
                step_name,
                decision=decision,
                actor=actor,
                note=note,
            )
        )


@workflow_app.command("retry")
def workflow_retry(
    run_id: str,
    from_step: str | None = typer.Option(None, "--from-step"),
) -> None:
    with session_scope(runtime().session_factory) as session:
        output(
            WorkflowService(
                session,
                cache_provider=runtime().cache_provider,
            ).retry(run_id, from_step=from_step)
        )


@workflow_app.command("cancel")
def workflow_cancel(run_id: str) -> None:
    with session_scope(runtime().session_factory) as session:
        output(
            WorkflowService(
                session,
                cache_provider=runtime().cache_provider,
            ).request_cancel(run_id)
        )


@memory_app.command("query")
def memory_query(
    project_id: str,
    query: str,
    kind: list[str] | None = typer.Option(None, "--kind"),
    limit: int = typer.Option(10, "--limit", min=1, max=100),
) -> None:
    with session_scope(runtime().session_factory) as session:
        service = runtime().memory_service(session)
        hits = service.search(project_id, query, kinds=kind, limit=limit)
        output(
            {
                "revision": service.state(project_id).revision,
                "hits": [hit.model_dump(mode="json") for hit in hits],
                "conflicts": [
                    conflict.model_dump(mode="json")
                    for conflict in service.preflight(
                        project_id,
                        query,
                        persist=False,
                    )
                ],
            }
        )


@memory_app.command("extract")
def memory_extract(project_id: str, draft_id: str) -> None:
    async def run() -> Any:
        with session_scope(runtime().session_factory) as session:
            return (
                await runtime()
                .memory_service(session)
                .extract_accepted_draft(
                    project_id,
                    draft_id,
                )
            )

    output(asyncio.run(run()))


@memory_app.command("invalidate")
def memory_invalidate(
    memory_id: str,
    reason: str = typer.Option(..., "--reason"),
) -> None:
    with session_scope(runtime().session_factory) as session:
        output(runtime().memory_service(session).invalidate(memory_id, reason=reason))


@memory_app.command("rebuild")
def memory_rebuild(project_id: str) -> None:
    async def run() -> Any:
        with session_scope(runtime().session_factory) as session:
            return await runtime().memory_service(session).rebuild(project_id)

    output(asyncio.run(run()))


@app.command("worker")
def worker(
    once: bool = typer.Option(False, "--once"),
    drain: bool = typer.Option(False, "--drain"),
    poll_interval: float | None = typer.Option(None, "--poll-interval", min=0),
) -> None:
    if once and drain:
        raise typer.BadParameter("--once and --drain cannot be used together")
    workflow_worker = WorkflowWorker(runtime())
    if once:
        output({"worked": asyncio.run(workflow_worker.run_once())})
        return
    if drain:
        drain_interval = max(
            0.25 if poll_interval is None else poll_interval,
            0.25,
        )
        asyncio.run(
            workflow_worker.run_forever(
                poll_interval=drain_interval,
                max_idle_polls=5,
            )
        )
        return
    try:
        asyncio.run(workflow_worker.run_forever(poll_interval=poll_interval))
    except KeyboardInterrupt:
        typer.echo("Worker stopped.")


@infra_app.command("check")
def infra_check() -> None:
    rt = runtime()
    checks: dict[str, bool] = {}
    try:
        checks["mysql"] = check_database(rt.engine)
    except Exception:
        checks["mysql"] = False
    try:
        checks["minio"] = rt.object_store.health()
    except Exception:
        checks["minio"] = False
    try:
        checks["milvus"] = rt.vector_store.health()
    except Exception:
        checks["milvus"] = False
    if rt.settings.cache_provider == "redis":
        checks["redis_optional"] = rt.cache_provider.health()
    checks["embedding_config"] = rt.settings.embedding_provider == "deterministic" or bool(
        rt.settings.qwen_api_key
    )
    checks["llm_config"] = rt.settings.llm_provider == "mock" or bool(
        rt.settings.deepseek_api_key or rt.settings.llm_api_key
    )
    output(checks)
    if not all(value for name, value in checks.items() if name != "redis_optional"):
        raise typer.Exit(1)


@db_app.command("init")
def db_init() -> None:
    provision_mysql()
    db_migrate()


@db_app.command("migrate")
def db_migrate() -> None:
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "head")
    typer.echo("MySQL schema is at the latest revision.")


@vector_app.command("rebuild")
def vector_rebuild(project_id: str) -> None:
    rt = runtime()
    with session_scope(rt.session_factory) as session:
        repositories = StoryBibleService(session).repositories
        repositories.projects.require(project_id)
        rt.vector_store.delete(project_id=project_id)
        chunks = repositories.document_chunks.list(project_id, limit=10_000)
        from novel_harness.providers.vectorstore import VectorRecord

        rows: list[tuple[str, str, str, int, str, str, dict[str, Any]]] = [
            (
                chunk.vector_id or f"{chunk.document_id}:{chunk.ordinal}",
                chunk.document_id,
                "document",
                chunk.ordinal,
                chunk.content_hash,
                chunk.preview,
                {"preview": chunk.preview},
            )
            for chunk in chunks
        ]
        research_count = 0
        for note in repositories.research.list(project_id, limit=10_000):
            source_url = str(note.source_url)
            if not _is_indexable_research_note(
                verification_status=note.verification_status,
                credibility_score=note.credibility_score,
                source_url=source_url,
            ):
                continue
            for ordinal, evidence in enumerate(note.evidence_snippets):
                rows.append(
                    (
                        f"research:{note.id}:{ordinal}",
                        note.id,
                        "research",
                        ordinal,
                        evidence.content_hash,
                        evidence.text,
                        {
                            "preview": evidence.text,
                            "source_url": source_url,
                            "source_title": note.source_title,
                            "verification_status": note.verification_status,
                            "credibility_score": note.credibility_score,
                        },
                    )
                )
                research_count += 1
        memories = repositories.memories.list_active(project_id, limit=100_000)
        for memory in memories:
            rows.append(
                (
                    f"memory:{memory.id}",
                    memory.id,
                    "memory",
                    0,
                    memory.source_hash,
                    memory.statement,
                    {
                        "preview": memory.statement,
                        "kind": memory.kind,
                        "subject": memory.subject,
                        "predicate": memory.predicate,
                        "canon_version": memory.canon_version,
                        "confidence": memory.confidence,
                    },
                )
            )
        vectors = rt.embedding_provider.embed_documents([row[5] for row in rows]) if rows else []
        records = [
            VectorRecord(
                id=record_id,
                project_id=project_id,
                source_id=source_id,
                source_type=source_type,
                chunk_ordinal=ordinal,
                content_hash=content_hash,
                embedding=vector,
                metadata=metadata,
            )
            for (
                record_id,
                source_id,
                source_type,
                ordinal,
                content_hash,
                _text,
                metadata,
            ), vector in zip(rows, vectors, strict=True)
        ]
        count = rt.vector_store.upsert(records) if records else 0
    output(
        {
            "project_id": project_id,
            "vectors": count,
            "documents": len(chunks),
            "research_evidence": research_count,
            "memories": len(memories),
        }
    )


def _is_indexable_research_note(
    *,
    verification_status: str,
    credibility_score: float,
    source_url: str,
) -> bool:
    if verification_status not in {"fetched", "corroborated"}:
        return False
    if credibility_score < 0.5:
        return False
    normalized_url = source_url.lower()
    return not any(
        marker in normalized_url
        for marker in ("captcha", "/challenge", "verifycaptcha", "wappass.baidu.com")
    )


if __name__ == "__main__":
    app()
