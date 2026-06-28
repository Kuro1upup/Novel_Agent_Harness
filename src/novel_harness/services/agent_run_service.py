"""Persisted and structured-log observability for agent invocations."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any, TypeVar
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from novel_harness.models import AgentRun, utc_now
from novel_harness.observability import capture_llm_usage, prompt_version
from novel_harness.storage import session_scope
from novel_harness.storage.repositories import Repositories

ResultT = TypeVar("ResultT")
logger = logging.getLogger("novel_harness.agent")


class AgentRunService:
    def __init__(
        self,
        session: Session,
        *,
        provider: Any | None,
        input_cost_per_million: float = 0.0,
        output_cost_per_million: float = 0.0,
        persistence_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self.repositories = Repositories(session)
        self.provider = provider
        self.input_cost_per_million = max(input_cost_per_million, 0.0)
        self.output_cost_per_million = max(output_cost_per_million, 0.0)
        self.persistence_factory = persistence_factory

    async def execute(
        self,
        project_id: str,
        agent_name: str,
        operation: Callable[[], Awaitable[ResultT]],
        *,
        input_summary: str = "",
        workflow_run_id: str | None = None,
    ) -> ResultT:
        provider_name = (
            type(self.provider).__name__ if self.provider is not None else "deterministic"
        )
        trace_id = str(uuid4())
        run = AgentRun(
            project_id=project_id,
            agent_name=agent_name,
            provider=provider_name,
            status="running",
            input_summary=input_summary[:1000],
            model=str(getattr(self.provider, "model", "") or ""),
            prompt_version=prompt_version(agent_name),
            workflow_run_id=workflow_run_id,
            trace_id=trace_id,
        )
        self._add(run)
        self._log("agent_started", run)
        started = perf_counter()
        try:
            with capture_llm_usage() as usage:
                result = await operation()
        except Exception as exc:
            finished = utc_now()
            failed = run.model_copy(
                update={
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:2000],
                    "finished_at": finished,
                    "duration_ms": int((perf_counter() - started) * 1000),
                }
            )
            self._update(failed)
            self._log("agent_failed", failed, level=logging.ERROR)
            raise
        finished = utc_now()
        cost = (
            usage.prompt_tokens * self.input_cost_per_million
            + usage.completion_tokens * self.output_cost_per_million
        ) / 1_000_000
        succeeded = run.model_copy(
            update={
                "status": "succeeded",
                "output_summary": type(result).__name__,
                "finished_at": finished,
                "duration_ms": int((perf_counter() - started) * 1000),
                "model": usage.model or run.model,
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "estimated_cost": cost,
                "metadata": {"llm_calls": usage.calls},
            }
        )
        self._update(succeeded)
        self._log("agent_succeeded", succeeded)
        return result

    def list(self, project_id: str, *, limit: int = 100) -> list[AgentRun]:
        self.repositories.projects.require(project_id)
        return self.repositories.agent_runs.list(project_id, limit=limit)

    def _add(self, run: AgentRun) -> None:
        if self.persistence_factory is None:
            self.repositories.agent_runs.add(run)
            return
        with session_scope(self.persistence_factory) as session:
            Repositories(session).agent_runs.add(run)

    def _update(self, run: AgentRun) -> None:
        if self.persistence_factory is None:
            self.repositories.agent_runs.update(run)
            return
        with session_scope(self.persistence_factory) as session:
            Repositories(session).agent_runs.update(run)

    @staticmethod
    def _log(event: str, run: AgentRun, *, level: int = logging.INFO) -> None:
        logger.log(
            level,
            json.dumps(
                {
                    "event": event,
                    "trace_id": run.trace_id,
                    "project_id": run.project_id,
                    "workflow_run_id": run.workflow_run_id,
                    "agent": run.agent_name,
                    "provider": run.provider,
                    "model": run.model,
                    "prompt_version": run.prompt_version,
                    "status": run.status,
                    "duration_ms": run.duration_ms,
                    "prompt_tokens": run.prompt_tokens,
                    "completion_tokens": run.completion_tokens,
                    "estimated_cost": run.estimated_cost,
                    "error_type": run.error_type,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
