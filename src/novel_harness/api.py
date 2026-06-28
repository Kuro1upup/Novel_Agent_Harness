"""FastAPI transport for the Novel Agent Harness."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import asdict
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from novel_harness.config import Settings
from novel_harness.exceptions import (
    ConfigurationError,
    DocumentError,
    NovelHarnessError,
    OriginalityError,
    WorkflowStateError,
)
from novel_harness.logging_config import configure_logging
from novel_harness.models import (
    CheckRequest,
    CheckResponse,
    ErrorResponse,
    MemoryInvalidateRequest,
    MemoryQueryRequest,
    MemoryQueryResponse,
    MemoryRecord,
    MemoryState,
    NovelProject,
    PlotPlan,
    PlotRequest,
    ProjectCreate,
    ResearchNote,
    ResearchRequest,
    StoryBible,
    StyleProfile,
    WorkflowApprovalRequest,
    WorkflowCreateRequest,
    WorkflowRetryRequest,
    WorkflowRun,
    WorkflowRunDetail,
    WriteRequest,
    WriteResponse,
)
from novel_harness.providers import ObjectStoreError, VectorStoreError
from novel_harness.runtime import Runtime
from novel_harness.services import ProjectService, StoryBibleService, WorkflowService
from novel_harness.storage import (
    ResourceNotFoundError,
    VersionConflictError,
    check_database,
    session_scope,
)


async def get_runtime(request: Request) -> Runtime:
    return request.app.state.runtime


async def get_session(
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> AsyncGenerator[Session, None]:
    with session_scope(runtime.session_factory) as session:
        yield session


RuntimeDep = Annotated[Runtime, Depends(get_runtime)]
SessionDep = Annotated[Session, Depends(get_session)]


def create_app(
    *,
    settings: Settings | None = None,
    runtime: Runtime | None = None,
) -> FastAPI:
    runtime = runtime or Runtime(settings)
    configure_logging(runtime.settings.log_level)
    app = FastAPI(
        title="Novel Agent Harness",
        version="0.1.0",
        description="Provider-neutral long-form fiction writing agent harness.",
    )
    app.state.runtime = runtime
    _register_error_handlers(app)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def readiness(rt: RuntimeDep) -> JSONResponse:
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
        required = [value for name, value in checks.items() if name != "redis_optional"]
        code = status.HTTP_200_OK if all(required) else status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(
            {"status": "ready" if code == 200 else "not_ready", "checks": checks},
            code,
        )

    @app.post("/projects", response_model=NovelProject, status_code=201)
    async def create_project(payload: ProjectCreate, session: SessionDep) -> NovelProject:
        return ProjectService(session).create(**payload.model_dump())

    @app.get("/projects", response_model=list[NovelProject])
    async def list_projects(session: SessionDep) -> list[NovelProject]:
        return ProjectService(session).list()

    @app.get("/projects/{project_id}", response_model=NovelProject)
    async def get_project(project_id: str, session: SessionDep) -> NovelProject:
        return ProjectService(session).get(project_id)

    @app.post("/projects/{project_id}/style/analyze", response_model=StyleProfile)
    async def analyze_style(
        project_id: str,
        session: SessionDep,
        rt: RuntimeDep,
        files: Annotated[list[UploadFile] | None, File()] = None,
        raw_text: Annotated[str | None, Form()] = None,
    ) -> StyleProfile:
        texts: list[str] = []
        document_ids: list[str] = []
        for upload in files or []:
            content = await upload.read(rt.settings.max_upload_bytes + 1)
            document, text = rt.document_service(session).ingest_bytes(
                project_id,
                upload.filename or "upload.txt",
                content,
                mime_type=upload.content_type,
            )
            texts.append(text)
            document_ids.append(document.id)
        if raw_text and raw_text.strip():
            texts.append(raw_text)
        if not texts:
            raise DocumentError("provide at least one file or raw_text")
        return await rt.generation_service(session).analyze_style(
            project_id, texts, source_document_ids=document_ids
        )

    @app.post("/projects/{project_id}/research", response_model=list[ResearchNote])
    async def research(
        project_id: str,
        payload: ResearchRequest,
        session: SessionDep,
        rt: RuntimeDep,
    ) -> list[ResearchNote]:
        return await rt.research_service(session).research(
            project_id,
            payload.topic,
            historical_context=payload.historical_context,
            keywords=payload.keywords,
        )

    @app.get("/projects/{project_id}/bible", response_model=StoryBible)
    async def get_bible(project_id: str, session: SessionDep) -> StoryBible:
        return StoryBibleService(session).get(project_id)

    @app.post("/projects/{project_id}/plot/plan", response_model=PlotPlan)
    async def plan(
        project_id: str,
        payload: PlotRequest,
        session: SessionDep,
        rt: RuntimeDep,
    ) -> PlotPlan:
        return await rt.generation_service(session).plan(project_id, payload.current, payload.goal)

    @app.post("/projects/{project_id}/write", response_model=WriteResponse)
    async def write(
        project_id: str,
        payload: WriteRequest,
        session: SessionDep,
        rt: RuntimeDep,
    ) -> WriteResponse:
        draft, issues, risks, originality, patch_id = await rt.generation_service(session).write(
            project_id, payload.goal, current_summary=payload.current
        )
        return WriteResponse(
            draft=draft,
            continuity_issues=issues,
            fact_risks=risks,
            originality=asdict(originality),
            canon_patch_id=patch_id,
        )

    @app.post("/projects/{project_id}/check", response_model=CheckResponse)
    async def check(
        project_id: str,
        payload: CheckRequest,
        session: SessionDep,
        rt: RuntimeDep,
    ) -> CheckResponse:
        issues, risks = await rt.generation_service(session).check(project_id, payload.draft)
        return CheckResponse(continuity_issues=issues, fact_risks=risks)

    @app.post("/drafts/{draft_id}/accept", response_model=StoryBible)
    async def accept_draft(draft_id: str, session: SessionDep) -> StoryBible:
        patches = [
            patch
            for project in ProjectService(session).list()
            for patch in StoryBibleService(session).repositories.canon_patches.list(project.id)
            if patch.draft_id == draft_id
        ]
        if not patches:
            raise ResourceNotFoundError(f"canon patch for draft {draft_id!r} not found")
        return StoryBibleService(session).accept_patch(patches[0].id)

    @app.post(
        "/projects/{project_id}/workflows",
        response_model=WorkflowRunDetail,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_workflow(
        project_id: str,
        payload: WorkflowCreateRequest,
        session: SessionDep,
        rt: RuntimeDep,
    ) -> WorkflowRunDetail:
        return WorkflowService(
            session,
            cache_provider=rt.cache_provider,
        ).create_chapter_workflow(
            project_id,
            **payload.model_dump(),
        )

    @app.get("/projects/{project_id}/workflows", response_model=list[WorkflowRun])
    async def list_workflows(
        project_id: str,
        session: SessionDep,
        run_status: str | None = None,
        limit: int = 100,
    ) -> list[WorkflowRun]:
        return WorkflowService(session).list_for_project(
            project_id,
            status=run_status,
            limit=min(max(limit, 1), 1000),
        )

    @app.get("/workflows/{run_id}", response_model=WorkflowRunDetail)
    async def get_workflow(run_id: str, session: SessionDep) -> WorkflowRunDetail:
        return WorkflowService(session).detail(run_id)

    @app.post(
        "/workflows/{run_id}/steps/{step_name}/approval",
        response_model=WorkflowRunDetail,
    )
    async def approve_workflow_step(
        run_id: str,
        step_name: str,
        payload: WorkflowApprovalRequest,
        session: SessionDep,
        rt: RuntimeDep,
    ) -> WorkflowRunDetail:
        return WorkflowService(
            session,
            cache_provider=rt.cache_provider,
        ).decide_approval(
            run_id,
            step_name,
            decision=payload.decision,
            actor=payload.actor,
            note=payload.note,
        )

    @app.post("/workflows/{run_id}/retry", response_model=WorkflowRunDetail)
    async def retry_workflow(
        run_id: str,
        payload: WorkflowRetryRequest,
        session: SessionDep,
        rt: RuntimeDep,
    ) -> WorkflowRunDetail:
        return WorkflowService(
            session,
            cache_provider=rt.cache_provider,
        ).retry(run_id, from_step=payload.from_step)

    @app.post("/workflows/{run_id}/cancel", response_model=WorkflowRunDetail)
    async def cancel_workflow(
        run_id: str,
        session: SessionDep,
        rt: RuntimeDep,
    ) -> WorkflowRunDetail:
        return WorkflowService(
            session,
            cache_provider=rt.cache_provider,
        ).request_cancel(run_id)

    @app.get("/projects/{project_id}/memory", response_model=list[MemoryRecord])
    async def list_memory(
        project_id: str,
        session: SessionDep,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        ProjectService(session).get(project_id)
        return StoryBibleService(session).repositories.memories.list_active(
            project_id,
            limit=min(max(limit, 1), 1000),
        )

    @app.get("/projects/{project_id}/memory/state", response_model=MemoryState)
    async def memory_state(
        project_id: str,
        session: SessionDep,
        rt: RuntimeDep,
    ) -> MemoryState:
        return rt.memory_service(session).state(project_id)

    @app.post(
        "/projects/{project_id}/memory/query",
        response_model=MemoryQueryResponse,
    )
    async def query_memory(
        project_id: str,
        payload: MemoryQueryRequest,
        session: SessionDep,
        rt: RuntimeDep,
    ) -> MemoryQueryResponse:
        service = rt.memory_service(session)
        hits = service.search(
            project_id,
            payload.query,
            kinds=payload.kinds,
            limit=payload.limit,
        )
        conflicts = service.preflight(
            project_id,
            payload.query,
            persist=False,
        )
        return MemoryQueryResponse(
            revision=service.state(project_id).revision,
            hits=hits,
            conflicts=conflicts,
        )

    @app.post("/memory/{memory_id}/invalidate", response_model=MemoryRecord)
    async def invalidate_memory(
        memory_id: str,
        payload: MemoryInvalidateRequest,
        session: SessionDep,
        rt: RuntimeDep,
    ) -> MemoryRecord:
        return rt.memory_service(session).invalidate(
            memory_id,
            reason=payload.reason,
        )

    @app.post("/projects/{project_id}/memory/rebuild")
    async def rebuild_memory(
        project_id: str,
        session: SessionDep,
        rt: RuntimeDep,
    ) -> dict[str, int]:
        return await rt.memory_service(session).rebuild(project_id)

    return app


def _register_error_handlers(app: FastAPI) -> None:
    def response(code: int, error: str, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=code,
            content=ErrorResponse(error=error, message=message).model_dump(),
        )

    @app.exception_handler(ResourceNotFoundError)
    async def not_found(_: Request, exc: ResourceNotFoundError) -> JSONResponse:
        return response(404, "not_found", str(exc))

    @app.exception_handler(VersionConflictError)
    async def conflict(_: Request, exc: VersionConflictError) -> JSONResponse:
        return response(409, "version_conflict", str(exc))

    @app.exception_handler(WorkflowStateError)
    async def workflow_conflict(_: Request, exc: WorkflowStateError) -> JSONResponse:
        return response(409, "workflow_state_conflict", str(exc))

    @app.exception_handler(OriginalityError)
    async def originality(_: Request, exc: OriginalityError) -> JSONResponse:
        return response(409, "originality_check_failed", str(exc))

    @app.exception_handler(ConfigurationError)
    async def configuration_error(_: Request, exc: ConfigurationError) -> JSONResponse:
        return response(503, "configuration_error", str(exc))

    async def bad_request(_: Request, exc: Exception) -> JSONResponse:
        return response(422, "invalid_request", str(exc))

    app.add_exception_handler(DocumentError, bad_request)
    app.add_exception_handler(ValueError, bad_request)

    for exception_type in (ObjectStoreError, VectorStoreError, SQLAlchemyError):
        app.add_exception_handler(
            exception_type,
            lambda _request, exc: response(503, "dependency_unavailable", str(exc)),
        )

    @app.exception_handler(NovelHarnessError)
    async def domain_error(_: Request, exc: NovelHarnessError) -> JSONResponse:
        return response(400, "domain_error", str(exc))


app = create_app()
