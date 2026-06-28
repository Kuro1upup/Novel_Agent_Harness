"""Persistent workflow lifecycle and state transitions."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from novel_harness.exceptions import WorkflowStateError
from novel_harness.models import (
    WorkflowEvent,
    WorkflowRun,
    WorkflowRunDetail,
    WorkflowStep,
    utc_now,
)
from novel_harness.providers.cache import CacheProvider, NullCacheProvider
from novel_harness.storage.repositories import Repositories

TERMINAL_RUN_STATUSES = {"succeeded", "failed", "cancelled"}
TERMINAL_STEP_STATUSES = {"succeeded", "skipped"}
CHAPTER_STEPS: tuple[tuple[str, bool], ...] = (
    ("research", False),
    ("research_approval", True),
    ("memory_preflight", False),
    ("memory_conflict_approval", True),
    ("plan", False),
    ("plot_approval", True),
    ("write", False),
    ("quality_gate", False),
    ("draft_approval", True),
    ("canon_commit", False),
    ("memory_extract", False),
)


class WorkflowService:
    def __init__(
        self,
        session: Session,
        *,
        cache_provider: CacheProvider | None = None,
    ) -> None:
        self.session = session
        self.repositories = Repositories(session)
        self.cache = cache_provider or NullCacheProvider()

    def create_chapter_workflow(
        self,
        project_id: str,
        *,
        goal: str,
        current: str = "",
        research_topic: str | None = None,
        auto_approve: bool = False,
        max_attempts: int = 3,
        idempotency_key: str | None = None,
    ) -> WorkflowRunDetail:
        self.repositories.projects.require(project_id)
        if not goal.strip():
            raise ValueError("goal must not be empty")
        if not 1 <= max_attempts <= 20:
            raise ValueError("max_attempts must be between 1 and 20")
        normalized_key = idempotency_key.strip() if idempotency_key else None
        if normalized_key:
            existing = self.repositories.workflow_runs.get_by_idempotency_key(
                project_id,
                normalized_key,
            )
            if existing is not None:
                return self.detail(existing.id)
        topic = research_topic.strip() if research_topic else None
        run = WorkflowRun(
            project_id=project_id,
            idempotency_key=normalized_key,
            parameters={
                "goal": goal.strip(),
                "current": current.strip(),
                "research_topic": topic,
                "auto_approve": auto_approve,
            },
            current_step="research" if topic else "memory_preflight",
        )
        self.repositories.workflow_runs.add(run)
        for position, (name, requires_approval) in enumerate(CHAPTER_STEPS):
            skip_research = topic is None and name in {"research", "research_approval"}
            step = WorkflowStep(
                project_id=project_id,
                run_id=run.id,
                name=name,
                position=position,
                status="skipped" if skip_research else "pending",
                max_attempts=max_attempts,
                requires_approval=requires_approval,
                finished_at=utc_now() if skip_research else None,
            )
            self.repositories.workflow_steps.add(step)
        self._event(run, "run_created", data={"workflow_type": run.workflow_type})
        return self.detail(run.id)

    def detail(self, run_id: str) -> WorkflowRunDetail:
        run = self.repositories.workflow_runs.require(run_id)
        return WorkflowRunDetail(
            run=run,
            steps=self.repositories.workflow_steps.list_for_run(run_id),
            events=self.repositories.workflow_events.list_for_run(run_id),
        )

    def list_for_project(
        self,
        project_id: str,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[WorkflowRun]:
        self.repositories.projects.require(project_id)
        return self.repositories.workflow_runs.list_for_project(
            project_id,
            status=status,
            limit=limit,
        )

    def claim_next(self, worker_id: str, *, lease_seconds: int = 300) -> WorkflowRun | None:
        if not worker_id.strip():
            raise ValueError("worker_id must not be empty")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        run = self.repositories.workflow_runs.claim_next(
            worker_id,
            lease_seconds=lease_seconds,
        )
        if run is not None:
            self._event(run, "run_claimed", data={"worker_id": worker_id})
        return run

    def prepare_claimed_step(
        self,
        run_id: str,
        *,
        worker_id: str,
    ) -> WorkflowStep | None:
        run = self.repositories.workflow_runs.require_for_update(run_id)
        if run.status != "running" or run.claimed_by != worker_id:
            raise WorkflowStateError("workflow is not claimed by this worker")
        if run.cancel_requested:
            self._cancel(run, reason="cancel requested")
            return None

        steps = self.repositories.workflow_steps.list_for_run(run.id)
        step = next(
            (item for item in steps if item.status not in TERMINAL_STEP_STATUSES),
            None,
        )
        if step is None:
            self._succeed(run)
            return None
        if step.status == "failed":
            self._fail_run(run, step.error or f"step {step.name} failed")
            return None
        if step.status == "waiting_approval":
            self._wait_for_approval(run, step)
            return None
        if step.requires_approval:
            no_conflict_approval_needed = (
                step.name == "memory_conflict_approval" and self._can_auto_approve(run, step)
            )
            if no_conflict_approval_needed or (
                bool(run.parameters.get("auto_approve")) and self._can_auto_approve(run, step)
            ):
                now = utc_now()
                step = step.model_copy(
                    update={
                        "status": "succeeded",
                        "approval_decision": "approved",
                        "result": {"actor": "automatic", "note": "auto_approve enabled"},
                        "finished_at": now,
                        "updated_at": now,
                    }
                )
                self.repositories.workflow_steps.update(step)
                self._event(
                    run,
                    "step_auto_approved",
                    step=step,
                    data={"step": step.name},
                )
                self._queue_or_finish(run)
            else:
                now = utc_now()
                step = step.model_copy(update={"status": "waiting_approval", "updated_at": now})
                self.repositories.workflow_steps.update(step)
                self._wait_for_approval(run, step)
                self._event(
                    run,
                    "approval_requested",
                    step=step,
                    data={"step": step.name},
                )
            return None

        if step.attempt >= step.max_attempts:
            self._fail_run(run, f"step {step.name} exhausted its retry budget")
            return None
        now = utc_now()
        step = step.model_copy(
            update={
                "status": "running",
                "attempt": step.attempt + 1,
                "started_at": now,
                "finished_at": None,
                "error": None,
                "updated_at": now,
            }
        )
        run = run.model_copy(update={"current_step": step.name, "updated_at": now})
        self.repositories.workflow_steps.update(step)
        self.repositories.workflow_runs.update(run)
        self._event(
            run,
            "step_started",
            step=step,
            data={"step": step.name, "attempt": step.attempt},
        )
        return step

    def complete_step(
        self,
        run_id: str,
        step_name: str,
        result: dict[str, Any],
        *,
        worker_id: str,
    ) -> WorkflowRun:
        run = self.repositories.workflow_runs.require_for_update(run_id)
        step = self._require_step(run_id, step_name, for_update=True)
        if run.claimed_by != worker_id or step.status != "running":
            raise WorkflowStateError("workflow step is not running for this worker")
        now = utc_now()
        step = step.model_copy(
            update={
                "status": "succeeded",
                "result": result,
                "finished_at": now,
                "updated_at": now,
            }
        )
        merged_result = dict(run.result)
        merged_result[step.name] = result
        run = run.model_copy(update={"result": merged_result, "updated_at": now})
        self.repositories.workflow_steps.update(step)
        self.repositories.workflow_runs.update(run)
        self._event(
            run,
            "step_succeeded",
            step=step,
            data={"step": step.name, "attempt": step.attempt},
        )
        if run.cancel_requested:
            return self._cancel(run, reason="cancel requested")
        return self._queue_or_finish(run)

    def fail_step(
        self,
        run_id: str,
        step_name: str,
        error: Exception,
        *,
        worker_id: str,
        retry_backoff_seconds: int = 5,
    ) -> WorkflowRun:
        run = self.repositories.workflow_runs.require_for_update(run_id)
        step = self._require_step(run_id, step_name, for_update=True)
        if run.claimed_by != worker_id or step.status != "running":
            raise WorkflowStateError("workflow step is not running for this worker")
        message = f"{type(error).__name__}: {error}"[:2000]
        now = utc_now()
        if step.attempt < step.max_attempts:
            step = step.model_copy(
                update={
                    "status": "pending",
                    "error": message,
                    "finished_at": now,
                    "updated_at": now,
                }
            )
            run = run.model_copy(
                update={
                    "status": "queued",
                    "available_at": now + timedelta(seconds=max(retry_backoff_seconds, 0)),
                    "claimed_by": None,
                    "claim_expires_at": None,
                    "error": message,
                    "updated_at": now,
                }
            )
            event_type = "step_retry_scheduled"
        else:
            step = step.model_copy(
                update={
                    "status": "failed",
                    "error": message,
                    "finished_at": now,
                    "updated_at": now,
                }
            )
            run = run.model_copy(
                update={
                    "status": "failed",
                    "claimed_by": None,
                    "claim_expires_at": None,
                    "finished_at": now,
                    "error": message,
                    "updated_at": now,
                }
            )
            event_type = "step_failed"
        self.repositories.workflow_steps.update(step)
        self.repositories.workflow_runs.update(run)
        self._event(
            run,
            event_type,
            step=step,
            data={"step": step.name, "attempt": step.attempt, "error": message},
        )
        return run

    def decide_approval(
        self,
        run_id: str,
        step_name: str,
        *,
        decision: str,
        actor: str,
        note: str = "",
    ) -> WorkflowRunDetail:
        run = self.repositories.workflow_runs.require_for_update(run_id)
        step = self._require_step(run_id, step_name, for_update=True)
        if run.status != "waiting_approval" or step.status != "waiting_approval":
            raise WorkflowStateError("workflow step is not waiting for approval")
        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")
        now = utc_now()
        approval_result = {"actor": actor, "note": note}
        if decision == "approve":
            step = step.model_copy(
                update={
                    "status": "succeeded",
                    "approval_decision": "approved",
                    "result": approval_result,
                    "finished_at": now,
                    "updated_at": now,
                }
            )
            self.repositories.workflow_steps.update(step)
            self._event(run, "step_approved", step=step, data=approval_result)
            self._queue_or_finish(run)
        else:
            step = step.model_copy(
                update={
                    "status": "failed",
                    "approval_decision": "rejected",
                    "result": approval_result,
                    "error": note or "approval rejected",
                    "finished_at": now,
                    "updated_at": now,
                }
            )
            self.repositories.workflow_steps.update(step)
            self._event(run, "step_rejected", step=step, data=approval_result)
            self._fail_run(run, step.error or "approval rejected")
        return self.detail(run_id)

    def request_cancel(self, run_id: str) -> WorkflowRunDetail:
        run = self.repositories.workflow_runs.require_for_update(run_id)
        if run.status in TERMINAL_RUN_STATUSES:
            return self.detail(run_id)
        run = run.model_copy(update={"cancel_requested": True, "updated_at": utc_now()})
        self.repositories.workflow_runs.update(run)
        self._event(run, "cancel_requested")
        if run.status != "running":
            self._cancel(run, reason="cancel requested")
        return self.detail(run_id)

    def retry(self, run_id: str, *, from_step: str | None = None) -> WorkflowRunDetail:
        run = self.repositories.workflow_runs.require_for_update(run_id)
        if run.status != "failed":
            raise WorkflowStateError("only failed workflows can be retried")
        steps = self.repositories.workflow_steps.list_for_run(run_id)
        target = (
            self._require_step(run_id, from_step, for_update=True)
            if from_step
            else next((step for step in steps if step.status == "failed"), None)
        )
        if target is None:
            raise WorkflowStateError("failed workflow has no failed step")
        reset_names: set[str] = set()
        for step in steps:
            if step.position < target.position:
                continue
            reset_names.add(step.name)
            step = step.model_copy(
                update={
                    "status": "pending",
                    "attempt": 0,
                    "approval_decision": None,
                    "result": {},
                    "started_at": None,
                    "finished_at": None,
                    "error": None,
                    "updated_at": utc_now(),
                }
            )
            self.repositories.workflow_steps.update(step)
        result = {key: value for key, value in run.result.items() if key not in reset_names}
        run = run.model_copy(
            update={
                "status": "queued",
                "result": result,
                "current_step": target.name,
                "cancel_requested": False,
                "available_at": utc_now(),
                "claimed_by": None,
                "claim_expires_at": None,
                "finished_at": None,
                "error": None,
                "updated_at": utc_now(),
            }
        )
        self.repositories.workflow_runs.update(run)
        self._event(run, "run_retried", step=target, data={"from_step": target.name})
        return self.detail(run_id)

    def _queue_or_finish(self, run: WorkflowRun) -> WorkflowRun:
        steps = self.repositories.workflow_steps.list_for_run(run.id)
        next_step = next(
            (step for step in steps if step.status not in TERMINAL_STEP_STATUSES),
            None,
        )
        if next_step is None:
            return self._succeed(run)
        now = utc_now()
        run = run.model_copy(
            update={
                "status": "queued",
                "current_step": next_step.name,
                "available_at": now,
                "claimed_by": None,
                "claim_expires_at": None,
                "error": None,
                "updated_at": now,
            }
        )
        self.repositories.workflow_runs.update(run)
        return run

    def _wait_for_approval(self, run: WorkflowRun, step: WorkflowStep) -> WorkflowRun:
        run = run.model_copy(
            update={
                "status": "waiting_approval",
                "current_step": step.name,
                "claimed_by": None,
                "claim_expires_at": None,
                "updated_at": utc_now(),
            }
        )
        self.repositories.workflow_runs.update(run)
        return run

    def _succeed(self, run: WorkflowRun) -> WorkflowRun:
        now = utc_now()
        run = run.model_copy(
            update={
                "status": "succeeded",
                "current_step": None,
                "claimed_by": None,
                "claim_expires_at": None,
                "finished_at": now,
                "error": None,
                "updated_at": now,
            }
        )
        self.repositories.workflow_runs.update(run)
        self._event(run, "run_succeeded")
        return run

    def _fail_run(self, run: WorkflowRun, error: str) -> WorkflowRun:
        now = utc_now()
        run = run.model_copy(
            update={
                "status": "failed",
                "claimed_by": None,
                "claim_expires_at": None,
                "finished_at": now,
                "error": error[:2000],
                "updated_at": now,
            }
        )
        self.repositories.workflow_runs.update(run)
        self._event(run, "run_failed", data={"error": run.error})
        return run

    def _cancel(self, run: WorkflowRun, *, reason: str) -> WorkflowRun:
        now = utc_now()
        for step in self.repositories.workflow_steps.list_for_run(run.id):
            if step.status in {"pending", "waiting_approval"}:
                self.repositories.workflow_steps.update(
                    step.model_copy(
                        update={"status": "skipped", "finished_at": now, "updated_at": now}
                    )
                )
        run = run.model_copy(
            update={
                "status": "cancelled",
                "claimed_by": None,
                "claim_expires_at": None,
                "finished_at": now,
                "error": reason,
                "updated_at": now,
            }
        )
        self.repositories.workflow_runs.update(run)
        self._event(run, "run_cancelled", data={"reason": reason})
        return run

    def _require_step(
        self,
        run_id: str,
        name: str,
        *,
        for_update: bool = False,
    ) -> WorkflowStep:
        step = (
            self.repositories.workflow_steps.get_for_run_for_update(run_id, name)
            if for_update
            else self.repositories.workflow_steps.get_for_run(run_id, name)
        )
        if step is None:
            raise WorkflowStateError(f"workflow step {name!r} was not found")
        return step

    def _event(
        self,
        run: WorkflowRun,
        event_type: str,
        *,
        step: WorkflowStep | None = None,
        data: dict[str, Any] | None = None,
    ) -> WorkflowEvent:
        event = WorkflowEvent(
            project_id=run.project_id,
            run_id=run.id,
            step_id=step.id if step else None,
            sequence=self.repositories.workflow_events.next_sequence(run.id),
            event_type=event_type,
            data=data or {},
        )
        stored = self.repositories.workflow_events.add(event)
        self.cache.publish(
            f"novel:workflow:events:{run.project_id}",
            stored.model_dump(mode="json"),
        )
        return stored

    @staticmethod
    def _can_auto_approve(run: WorkflowRun, step: WorkflowStep) -> bool:
        if step.name == "research_approval":
            research = run.result.get("research")
            if not isinstance(research, dict):
                return False
            sources = research.get("sources")
            if not isinstance(sources, list):
                return False
            for source in sources:
                if not isinstance(source, dict):
                    continue
                try:
                    credibility = float(source.get("credibility_score", 0))
                except (TypeError, ValueError):
                    continue
                if (
                    source.get("verification_status") in {"fetched", "corroborated"}
                    and credibility >= 0.5
                ):
                    return True
            return False
        if step.name == "draft_approval":
            quality = run.result.get("quality_gate")
            return isinstance(quality, dict) and quality.get("passed") is True
        if step.name == "memory_conflict_approval":
            preflight = run.result.get("memory_preflight")
            return isinstance(preflight, dict) and int(preflight.get("hard_conflicts", 0)) == 0
        return True
