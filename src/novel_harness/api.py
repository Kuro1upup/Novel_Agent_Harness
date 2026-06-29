"""FastAPI transport for the Novel Agent Harness."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from novel_harness.config import Settings
from novel_harness.exceptions import (
    AuthenticationError,
    BillingUnavailableError,
    ConfigurationError,
    DocumentError,
    InsufficientBalanceError,
    NovelHarnessError,
    OriginalityError,
    ProjectArchivedError,
    WorkflowStateError,
)
from novel_harness.integrations import AuthenticatedUser, ServiceClient
from novel_harness.logging_config import configure_logging
from novel_harness.models import (
    AgentRun,
    BibleEntryRequest,
    CharacterProposalRequest,
    CharacterProposalResponse,
    CheckRequest,
    CheckResponse,
    DraftDiffResponse,
    DraftRejectRequest,
    DraftRevisionRequest,
    ErrorResponse,
    ForeshadowingCreateRequest,
    ForeshadowingProposalRequest,
    ForeshadowingProposalResponse,
    ForeshadowingResolveRequest,
    GenerationResult,
    MemoryInvalidateRequest,
    MemoryQueryRequest,
    MemoryQueryResponse,
    MemoryRecord,
    MemoryState,
    NovelProject,
    PlotPlan,
    PlotRequest,
    PlotSelectionRequest,
    ProjectCreate,
    ProjectUpdate,
    ResearchNote,
    ResearchRequest,
    StoryBible,
    StyleProfile,
    TimelineEventRequest,
    WorkflowApprovalRequest,
    WorkflowCreateRequest,
    WorkflowRetryRequest,
    WorkflowRun,
    WorkflowRunDetail,
    WorldbuildingProposalRequest,
    WorldbuildingProposalResponse,
    WriteRequest,
    WriteResponse,
)
from novel_harness.providers import ObjectStoreError, VectorStoreError
from novel_harness.runtime import Runtime
from novel_harness.security import bind_user, reset_user
from novel_harness.services import ProjectService, StoryBibleService, WorkflowService
from novel_harness.storage import (
    ResourceNotFoundError,
    VersionConflictError,
    check_database,
    session_scope,
)

logger = logging.getLogger("novel_harness.api")

_PUBLIC_PATHS = {
    "/health",
    "/health/ready",
    "/docs",
    "/docs/oauth2-redirect",
    "/openapi.json",
    "/redoc",
}


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
    configure_logging(
        runtime.settings.log_level,
        log_file=runtime.settings.log_file,
        max_bytes=runtime.settings.log_max_bytes,
        backup_count=runtime.settings.log_backup_count,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
        logger.info(json.dumps({"event": "api_started"}, separators=(",", ":")))
        try:
            yield
        finally:
            logger.info(json.dumps({"event": "api_stopping"}, separators=(",", ":")))
            await runtime.aclose()

    app = FastAPI(
        title="Novel Agent Harness",
        version="0.3.0",
        description="Provider-neutral long-form fiction writing agent harness.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=runtime.settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.runtime = runtime
    _register_error_handlers(app)

    @app.middleware("http")
    async def authenticate_request(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        is_public = (
            request.method == "OPTIONS" or path in _PUBLIC_PATHS or path.startswith("/api/auth/")
        )
        if is_public:
            return await call_next(request)

        if runtime.settings.auth_required:
            authorization = request.headers.get("Authorization", "")
            scheme, _, token = authorization.partition(" ")
            if scheme.lower() != "bearer" or not token.strip():
                return _api_error(401, "unauthorized", "未提供有效的 Bearer Token")
            try:
                user = await runtime.auth_client.verify(token.strip())
            except AuthenticationError as exc:
                return _api_error(401, "unauthorized", str(exc))
        else:
            user = AuthenticatedUser(id=1, nickname="Development User")

        request.state.current_user = user
        context_token = bind_user(user.id)
        try:
            return await call_next(request)
        finally:
            reset_user(context_token)

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
        if rt.settings.auth_required:
            checks["auth"] = await rt.auth_client.health()
        if rt.settings.billing_enabled:
            checks["billing"] = await rt.billing_client.health()
        checks["embedding_config"] = rt.settings.embedding_provider == "deterministic" or bool(
            rt.settings.qwen_api_key
        )
        checks["llm_config"] = rt.settings.llm_provider == "mock" or bool(
            rt.settings.deepseek_api_key or rt.settings.llm_api_key
        )
        required = [value for name, value in checks.items() if name != "redis_optional"]
        code = status.HTTP_200_OK if all(required) else status.HTTP_503_SERVICE_UNAVAILABLE
        if code != status.HTTP_200_OK:
            logger.warning(
                json.dumps(
                    {"event": "readiness_failed", "checks": checks},
                    separators=(",", ":"),
                )
            )
        return JSONResponse(
            {"status": "ready" if code == 200 else "not_ready", "checks": checks},
            code,
        )

    @app.api_route(
        "/api/auth/{upstream_path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    )
    async def proxy_auth(upstream_path: str, request: Request, rt: RuntimeDep) -> Response:
        return await _proxy_request(
            request,
            rt.auth_client,
            f"/api/auth/{upstream_path}",
        )

    @app.api_route(
        "/api/billing/{upstream_path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    )
    async def proxy_billing(upstream_path: str, request: Request, rt: RuntimeDep) -> Response:
        if upstream_path == "internal" or upstream_path.startswith("internal/"):
            return _api_error(404, "not_found", "接口不存在")
        return await _proxy_request(
            request,
            rt.billing_client,
            f"/api/billing/{upstream_path}",
        )

    @app.post("/projects", response_model=NovelProject, status_code=201)
    async def create_project(
        payload: ProjectCreate,
        request: Request,
        session: SessionDep,
    ) -> NovelProject:
        return ProjectService(session).create(
            owner_user_id=_current_user(request).id,
            **payload.model_dump(),
        )

    @app.get("/projects", response_model=list[NovelProject])
    async def list_projects(
        session: SessionDep,
        include_archived: bool = False,
    ) -> list[NovelProject]:
        return ProjectService(session).list(include_archived=include_archived)

    @app.get("/projects/{project_id}", response_model=NovelProject)
    async def get_project(project_id: str, session: SessionDep) -> NovelProject:
        return ProjectService(session).get(project_id)

    @app.patch("/projects/{project_id}", response_model=NovelProject)
    async def update_project(
        project_id: str,
        payload: ProjectUpdate,
        session: SessionDep,
    ) -> NovelProject:
        return ProjectService(session).update(
            project_id,
            **payload.model_dump(exclude_unset=True),
        )

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

    @app.post(
        "/projects/{project_id}/agents/character",
        response_model=CharacterProposalResponse,
    )
    async def propose_character(
        project_id: str,
        payload: CharacterProposalRequest,
        session: SessionDep,
        rt: RuntimeDep,
    ) -> CharacterProposalResponse:
        proposal, bible = await rt.creative_service(session).propose_character(
            project_id,
            **payload.model_dump(),
        )
        return CharacterProposalResponse(proposal=proposal, bible=bible)

    @app.post(
        "/projects/{project_id}/agents/worldbuilding",
        response_model=WorldbuildingProposalResponse,
    )
    async def propose_worldbuilding(
        project_id: str,
        payload: WorldbuildingProposalRequest,
        session: SessionDep,
        rt: RuntimeDep,
    ) -> WorldbuildingProposalResponse:
        proposal, bible = await rt.creative_service(session).propose_worldbuilding(
            project_id,
            **payload.model_dump(),
        )
        return WorldbuildingProposalResponse(proposal=proposal, bible=bible)

    @app.post(
        "/projects/{project_id}/agents/foreshadowing",
        response_model=ForeshadowingProposalResponse,
    )
    async def propose_foreshadowing(
        project_id: str,
        payload: ForeshadowingProposalRequest,
        session: SessionDep,
        rt: RuntimeDep,
    ) -> ForeshadowingProposalResponse:
        proposal, bible = await rt.creative_service(session).propose_foreshadowing(
            project_id,
            **payload.model_dump(),
        )
        return ForeshadowingProposalResponse(proposal=proposal, bible=bible)

    @app.post("/projects/{project_id}/bible/rules", response_model=StoryBible)
    async def add_bible_rule(
        project_id: str,
        payload: BibleEntryRequest,
        session: SessionDep,
    ) -> StoryBible:
        return StoryBibleService(session).add_rule(
            project_id,
            payload.value,
            expected_version=payload.expected_version,
        )

    @app.post("/projects/{project_id}/bible/factions", response_model=StoryBible)
    async def add_bible_faction(
        project_id: str,
        payload: BibleEntryRequest,
        session: SessionDep,
    ) -> StoryBible:
        if not isinstance(payload.value, dict):
            raise ValueError("faction must be an object")
        return StoryBibleService(session).add_faction(
            project_id,
            payload.value,
            expected_version=payload.expected_version,
        )

    @app.post("/projects/{project_id}/bible/locations", response_model=StoryBible)
    async def add_bible_location(
        project_id: str,
        payload: BibleEntryRequest,
        session: SessionDep,
    ) -> StoryBible:
        if not isinstance(payload.value, dict):
            raise ValueError("location must be an object")
        return StoryBibleService(session).add_location(
            project_id,
            payload.value,
            expected_version=payload.expected_version,
        )

    @app.post("/projects/{project_id}/bible/timeline", response_model=StoryBible)
    async def add_bible_timeline(
        project_id: str,
        payload: TimelineEventRequest,
        session: SessionDep,
    ) -> StoryBible:
        return StoryBibleService(session).add_timeline_event(
            project_id,
            payload.to_event(project_id),
            expected_version=payload.expected_version,
        )

    @app.post("/projects/{project_id}/bible/foreshadowing", response_model=StoryBible)
    async def add_bible_foreshadowing(
        project_id: str,
        payload: ForeshadowingCreateRequest,
        session: SessionDep,
    ) -> StoryBible:
        return StoryBibleService(session).add_foreshadowing(
            project_id,
            payload.description,
            planted_at=payload.planted_at,
            expected_payoff=payload.expected_payoff,
            expected_version=payload.expected_version,
        )

    @app.post(
        "/projects/{project_id}/bible/foreshadowing/{item_id}/resolve",
        response_model=StoryBible,
    )
    async def resolve_bible_foreshadowing(
        project_id: str,
        item_id: str,
        payload: ForeshadowingResolveRequest,
        session: SessionDep,
    ) -> StoryBible:
        return StoryBibleService(session).resolve_foreshadowing(
            project_id,
            item_id,
            resolution=payload.resolution,
            expected_version=payload.expected_version,
        )

    @app.post("/projects/{project_id}/plot/plan", response_model=PlotPlan)
    async def plan(
        project_id: str,
        payload: PlotRequest,
        session: SessionDep,
        rt: RuntimeDep,
    ) -> PlotPlan:
        return await rt.generation_service(session).plan(project_id, payload.current, payload.goal)

    @app.post(
        "/projects/{project_id}/plot/plans/{plan_id}/select",
        response_model=PlotPlan,
    )
    async def select_plot_option(
        project_id: str,
        plan_id: str,
        payload: PlotSelectionRequest,
        session: SessionDep,
        rt: RuntimeDep,
    ) -> PlotPlan:
        return rt.generation_service(session).select_plot_option(
            project_id,
            plan_id,
            payload.option_id,
        )

    @app.post("/projects/{project_id}/write", response_model=WriteResponse)
    async def write(
        project_id: str,
        payload: WriteRequest,
        session: SessionDep,
        rt: RuntimeDep,
    ) -> WriteResponse:
        generation = rt.generation_service(session)
        plot_plan = (
            generation.repositories.plot_plans.require(payload.plot_plan_id)
            if payload.plot_plan_id
            else None
        )
        draft, issues, risks, originality, patch_id = await generation.write(
            project_id,
            payload.goal,
            current_summary=payload.current,
            plot_plan=plot_plan,
            selected_option_id=payload.selected_option_id,
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
        service = StoryBibleService(session)
        patch = service.repositories.canon_patches.get_by_draft(draft_id)
        if patch is None:
            raise ResourceNotFoundError(f"canon patch for draft {draft_id!r} not found")
        return service.accept_patch(patch.id)

    @app.get("/projects/{project_id}/drafts", response_model=list[GenerationResult])
    async def list_drafts(
        project_id: str,
        session: SessionDep,
        rt: RuntimeDep,
        draft_status: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[GenerationResult]:
        return rt.generation_service(session).list_drafts(
            project_id,
            status=draft_status,
            offset=max(offset, 0),
            limit=min(max(limit, 1), 1000),
        )

    @app.get("/drafts/{draft_id}", response_model=GenerationResult)
    async def get_draft(
        draft_id: str,
        session: SessionDep,
        rt: RuntimeDep,
    ) -> GenerationResult:
        return rt.generation_service(session).get_draft(draft_id)

    @app.get("/drafts/{draft_id}/download")
    async def download_draft(
        draft_id: str,
        session: SessionDep,
        rt: RuntimeDep,
    ) -> Response:
        draft = rt.generation_service(session).get_draft(draft_id)
        return PlainTextResponse(
            draft.body,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{draft.id}.md"'},
        )

    @app.post("/drafts/{draft_id}/reject", response_model=GenerationResult)
    async def reject_draft(
        draft_id: str,
        payload: DraftRejectRequest,
        session: SessionDep,
        rt: RuntimeDep,
    ) -> GenerationResult:
        return rt.generation_service(session).reject_draft(
            draft_id,
            reason=payload.reason,
        )

    @app.post("/drafts/{draft_id}/revise", response_model=WriteResponse)
    async def revise_draft(
        draft_id: str,
        payload: DraftRevisionRequest,
        session: SessionDep,
        rt: RuntimeDep,
    ) -> WriteResponse:
        draft, issues, risks, originality, patch_id = await rt.generation_service(
            session
        ).revise_draft(
            draft_id,
            instruction=payload.instruction,
        )
        return WriteResponse(
            draft=draft,
            continuity_issues=issues,
            fact_risks=risks,
            originality=asdict(originality),
            canon_patch_id=patch_id,
        )

    @app.get(
        "/drafts/{from_draft_id}/diff/{to_draft_id}",
        response_model=DraftDiffResponse,
    )
    async def compare_drafts(
        from_draft_id: str,
        to_draft_id: str,
        session: SessionDep,
        rt: RuntimeDep,
    ) -> DraftDiffResponse:
        return DraftDiffResponse(
            from_draft_id=from_draft_id,
            to_draft_id=to_draft_id,
            unified_diff=rt.generation_service(session).compare_drafts(
                from_draft_id,
                to_draft_id,
            ),
        )

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
            selected_option_id=payload.selected_option_id,
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

    @app.get("/projects/{project_id}/agent-runs", response_model=list[AgentRun])
    async def list_agent_runs(
        project_id: str,
        session: SessionDep,
        rt: RuntimeDep,
        limit: int = 100,
    ) -> list[AgentRun]:
        return rt.agent_run_service(session).list(
            project_id,
            limit=min(max(limit, 1), 1000),
        )

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

    @app.exception_handler(BillingUnavailableError)
    async def billing_unavailable(_: Request, exc: BillingUnavailableError) -> JSONResponse:
        return response(503, "billing_unavailable", str(exc))

    @app.exception_handler(InsufficientBalanceError)
    async def insufficient_balance(_: Request, exc: InsufficientBalanceError) -> JSONResponse:
        return response(402, "insufficient_balance", str(exc))

    @app.exception_handler(ProjectArchivedError)
    async def project_archived(_: Request, exc: ProjectArchivedError) -> JSONResponse:
        return response(409, "project_archived", str(exc))

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


def _current_user(request: Request) -> AuthenticatedUser:
    user = getattr(request.state, "current_user", None)
    if not isinstance(user, AuthenticatedUser):
        raise AuthenticationError("未找到当前登录用户")
    return user


def _api_error(status_code: int, error: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": error, "message": message},
    )


async def _proxy_request(
    request: Request,
    client: ServiceClient,
    path: str,
) -> Response:
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() in {"accept", "authorization", "content-type"}
    }
    try:
        upstream = await client.request(
            request.method,
            path,
            headers=headers,
            params=request.query_params.multi_items(),
            content=await request.body(),
        )
    except ConnectionError:
        return _api_error(503, "upstream_unavailable", "上游服务暂时不可用")
    response_headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() in {"content-type", "content-disposition", "cache-control"}
    }
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
    )


app = create_app()
