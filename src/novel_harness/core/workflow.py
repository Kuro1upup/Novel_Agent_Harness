"""MySQL-backed workflow worker and step executor."""

from __future__ import annotations

import asyncio
import os
import socket
from dataclasses import asdict
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from novel_harness.models import WorkflowRun, WorkflowStep
from novel_harness.services import StoryBibleService, WorkflowService
from novel_harness.storage import session_scope

if TYPE_CHECKING:
    from novel_harness.runtime import Runtime
    from novel_harness.storage.repositories import Repositories


class WorkflowWorker:
    """Claim and execute one durable workflow step at a time."""

    def __init__(
        self,
        runtime: Runtime,
        *,
        worker_id: str | None = None,
        lease_seconds: int | None = None,
        retry_backoff_seconds: int | None = None,
    ) -> None:
        self.runtime = runtime
        self.worker_id = worker_id or (f"{socket.gethostname()}:{os.getpid()}:{str(uuid4())[:8]}")
        self.lease_seconds = lease_seconds or runtime.settings.workflow_lease_seconds
        self.retry_backoff_seconds = (
            runtime.settings.workflow_retry_backoff_seconds
            if retry_backoff_seconds is None
            else retry_backoff_seconds
        )

    async def run_once(self) -> bool:
        with session_scope(self.runtime.session_factory) as session:
            run = WorkflowService(
                session,
                cache_provider=self.runtime.cache_provider,
            ).claim_next(
                self.worker_id,
                lease_seconds=self.lease_seconds,
            )
            run_id = run.id if run else None
        if run_id is None:
            return False

        with session_scope(self.runtime.session_factory) as session:
            step = WorkflowService(
                session,
                cache_provider=self.runtime.cache_provider,
            ).prepare_claimed_step(
                run_id,
                worker_id=self.worker_id,
            )
            step_name = step.name if step else None
        if step_name is None:
            return True

        try:
            with session_scope(self.runtime.session_factory) as session:
                service = WorkflowService(
                    session,
                    cache_provider=self.runtime.cache_provider,
                )
                run = service.repositories.workflow_runs.require(run_id)
                step = service.repositories.workflow_steps.get_for_run(run_id, step_name)
                if step is None:
                    raise RuntimeError(f"workflow step {step_name!r} disappeared")
                result = await self._execute_step(run, step, service.repositories, session)
                service.complete_step(
                    run_id,
                    step_name,
                    result,
                    worker_id=self.worker_id,
                )
        except Exception as exc:
            with session_scope(self.runtime.session_factory) as session:
                WorkflowService(
                    session,
                    cache_provider=self.runtime.cache_provider,
                ).fail_step(
                    run_id,
                    step_name,
                    exc,
                    worker_id=self.worker_id,
                    retry_backoff_seconds=self.retry_backoff_seconds,
                )
        return True

    async def run_forever(
        self,
        *,
        poll_interval: float | None = None,
        max_idle_polls: int | None = None,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        interval = (
            self.runtime.settings.worker_poll_interval_seconds
            if poll_interval is None
            else poll_interval
        )
        if interval < 0:
            raise ValueError("poll_interval must not be negative")
        idle_polls = 0
        while True:
            if stop_event is not None and stop_event.is_set():
                return
            worked = await self.run_once()
            if worked:
                idle_polls = 0
                continue
            idle_polls += 1
            if max_idle_polls is not None and idle_polls >= max_idle_polls:
                return
            if stop_event is None:
                await asyncio.sleep(interval)
                continue
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except TimeoutError:
                continue

    async def _execute_step(
        self,
        run: WorkflowRun,
        step: WorkflowStep,
        repositories: Repositories,
        session: Any,
    ) -> dict[str, Any]:
        project_id = run.project_id
        goal = str(run.parameters["goal"])
        current = str(run.parameters.get("current") or "")
        chapter_id = str(run.parameters["chapter_id"]) if run.parameters.get("chapter_id") else None

        if step.name == "research":
            topic = str(run.parameters.get("research_topic") or goal)
            notes = await self.runtime.research_service(session).research(project_id, topic)
            return {
                "topic": topic,
                "note_ids": [note.id for note in notes],
                "sources": [
                    {
                        "url": str(note.source_url),
                        "verification_status": note.verification_status,
                        "credibility_score": note.credibility_score,
                    }
                    for note in notes
                ],
            }
        if step.name == "memory_preflight":
            conflicts = self.runtime.memory_service(session).preflight(
                project_id,
                "\n".join(part for part in (current, goal) if part),
                run_id=run.id,
            )
            return {
                "conflict_ids": [conflict.id for conflict in conflicts],
                "hard_conflicts": sum(conflict.severity == "hard" for conflict in conflicts),
                "soft_conflicts": sum(conflict.severity == "soft" for conflict in conflicts),
                "conflicts": [conflict.model_dump(mode="json") for conflict in conflicts],
            }
        if step.name == "plan":
            plan = await self.runtime.generation_service(session).plan(
                project_id,
                current or "当前章节之后",
                goal,
                workflow_run_id=run.id,
            )
            return {
                "plan_id": plan.id,
                "bible_version": plan.bible_version,
                "options": [
                    {
                        "id": option.id,
                        "title": option.title,
                        "conflict": option.conflict,
                    }
                    for option in plan.next_chapter_options
                    if not isinstance(option, dict)
                ],
            }
        if step.name == "write":
            plan_result = run.result.get("plan")
            if not isinstance(plan_result, dict) or not plan_result.get("plan_id"):
                raise RuntimeError("workflow plan output is missing")
            plan = repositories.plot_plans.require(str(plan_result["plan_id"]))
            draft, issues, risks, originality, patch_id = await self.runtime.generation_service(
                session
            ).write(
                project_id,
                goal,
                current_summary=current,
                plot_plan=plan,
                selected_option_id=(
                    str(run.parameters["selected_option_id"])
                    if run.parameters.get("selected_option_id")
                    else None
                ),
                chapter_id=chapter_id,
                workflow_run_id=run.id,
            )
            return {
                "draft_id": draft.id,
                "chapter_id": chapter_id,
                "object_key": draft.object_key,
                "canon_patch_id": patch_id,
                "continuity_issue_ids": [issue.id for issue in issues],
                "fact_risk_ids": [risk.id for risk in risks],
                "continuity_errors": sum(issue.severity == "error" for issue in issues),
                "high_fact_risks": sum(risk.risk_level in {"high", "unknown"} for risk in risks),
                "context_source_count": len(draft.context_sources),
                "originality": asdict(originality),
            }
        if step.name == "quality_gate":
            write_result = run.result.get("write")
            if not isinstance(write_result, dict):
                raise RuntimeError("workflow write output is missing")
            continuity_errors = int(write_result.get("continuity_errors", 0))
            high_fact_risks = int(write_result.get("high_fact_risks", 0))
            return {
                "passed": continuity_errors == 0 and high_fact_risks == 0,
                "continuity_errors": continuity_errors,
                "high_fact_risks": high_fact_risks,
                "requires_author_review": (continuity_errors > 0 or high_fact_risks > 0),
            }
        if step.name == "canon_commit":
            write_result = run.result.get("write")
            if not isinstance(write_result, dict) or not write_result.get("canon_patch_id"):
                raise RuntimeError("workflow canon patch output is missing")
            bible = StoryBibleService(session).accept_patch(str(write_result["canon_patch_id"]))
            return {"bible_id": bible.id, "bible_version": bible.version}
        if step.name == "memory_extract":
            write_result = run.result.get("write")
            canon_result = run.result.get("canon_commit")
            if not isinstance(write_result, dict) or not write_result.get("draft_id"):
                raise RuntimeError("workflow accepted draft output is missing")
            if not isinstance(canon_result, dict) or not canon_result.get("bible_version"):
                raise RuntimeError("workflow canon commit output is missing")
            memories = await self.runtime.memory_service(session).extract_accepted_draft(
                project_id,
                str(write_result["draft_id"]),
                canon_version=int(canon_result["bible_version"]),
            )
            return {
                "memory_ids": [memory.id for memory in memories],
                "memory_count": len(memories),
                "canon_version": int(canon_result["bible_version"]),
            }
        raise RuntimeError(f"no executor registered for workflow step {step.name!r}")
