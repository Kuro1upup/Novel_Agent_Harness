from __future__ import annotations

from datetime import timedelta

import pytest

from novel_harness.core.workflow import WorkflowWorker
from novel_harness.models import PlotOption, PlotPlan, utc_now
from novel_harness.services import ProjectService, StoryBibleService, WorkflowService
from novel_harness.storage import session_scope


def test_workflow_waits_for_and_accepts_plot_approval(session) -> None:
    project = ProjectService(session).create(name="长安", genre="历史")
    service = WorkflowService(session)
    detail = service.create_chapter_workflow(
        project.id,
        goal="进入长安",
        current="主角抵达城外",
    )

    assert detail.run.status == "queued"
    assert [step.name for step in detail.steps] == [
        "research",
        "research_approval",
        "memory_preflight",
        "memory_conflict_approval",
        "plan",
        "plot_approval",
        "write",
        "quality_gate",
        "draft_approval",
        "canon_commit",
        "memory_extract",
    ]
    assert detail.steps[0].status == "skipped"
    assert detail.steps[1].status == "skipped"

    claimed = service.claim_next("worker-1")
    assert claimed is not None
    step = service.prepare_claimed_step(claimed.id, worker_id="worker-1")
    assert step is not None and step.name == "memory_preflight"
    service.complete_step(
        claimed.id,
        "memory_preflight",
        {"hard_conflicts": 0, "soft_conflicts": 0, "conflicts": []},
        worker_id="worker-1",
    )

    claimed = service.claim_next("worker-1")
    assert claimed is not None
    assert service.prepare_claimed_step(claimed.id, worker_id="worker-1") is None

    claimed = service.claim_next("worker-1")
    assert claimed is not None
    step = service.prepare_claimed_step(claimed.id, worker_id="worker-1")
    assert step is not None and step.name == "plan"
    service.complete_step(
        claimed.id,
        "plan",
        {"plan_id": "plan-1"},
        worker_id="worker-1",
    )

    claimed = service.claim_next("worker-1")
    assert claimed is not None
    assert service.prepare_claimed_step(claimed.id, worker_id="worker-1") is None
    waiting = service.detail(claimed.id)
    assert waiting.run.status == "waiting_approval"
    assert waiting.run.current_step == "plot_approval"

    approved = service.decide_approval(
        claimed.id,
        "plot_approval",
        decision="approve",
        actor="author",
        note="采用第一方案",
    )
    assert approved.run.status == "queued"
    assert approved.run.current_step == "write"
    assert next(step for step in approved.steps if step.name == "plot_approval").result == {
        "actor": "author",
        "note": "采用第一方案",
    }


def test_plot_approval_persists_explicit_option_selection(session) -> None:
    project = ProjectService(session).create(name="长安", genre="历史")
    service = WorkflowService(session)
    plan = PlotPlan(project_id=project.id, current_arc="入城")
    option = PlotOption(
        project_id=project.id,
        plot_plan_id=plan.id,
        title="主动查验",
        summary="主角主动寻找文书漏洞",
    )
    plan = plan.model_copy(update={"next_chapter_options": [option]})
    service.repositories.plot_plans.add(plan)
    service.repositories.plot_options.add(option)
    detail = service.create_chapter_workflow(project.id, goal="进入长安")
    run = detail.run.model_copy(
        update={
            "status": "waiting_approval",
            "current_step": "plot_approval",
            "result": {"plan": {"plan_id": plan.id}},
        }
    )
    service.repositories.workflow_runs.update(run)
    for step in detail.steps:
        if step.name == "plot_approval":
            service.repositories.workflow_steps.update(
                step.model_copy(update={"status": "waiting_approval"})
            )

    approved = service.decide_approval(
        run.id,
        "plot_approval",
        decision="approve",
        actor="author",
        selected_option_id=option.id,
    )

    assert approved.run.parameters["selected_option_id"] == option.id
    assert service.repositories.plot_plans.require(plan.id).selected_option_id == option.id
    approval = next(step for step in approved.steps if step.name == "plot_approval")
    assert approval.result["selected_option_id"] == option.id


def test_failed_workflow_can_be_retried_from_failed_step(session) -> None:
    project = ProjectService(session).create(name="长安", genre="历史")
    service = WorkflowService(session)
    run = service.create_chapter_workflow(
        project.id,
        goal="进入长安",
        max_attempts=1,
    ).run
    claimed = service.claim_next("worker-1")
    assert claimed is not None
    step = service.prepare_claimed_step(run.id, worker_id="worker-1")
    assert step is not None

    failed = service.fail_step(
        run.id,
        step.name,
        RuntimeError("provider unavailable"),
        worker_id="worker-1",
        retry_backoff_seconds=0,
    )
    assert failed.status == "failed"

    retried = service.retry(run.id)
    assert retried.run.status == "queued"
    reset = next(item for item in retried.steps if item.name == step.name)
    assert reset.status == "pending"
    assert reset.attempt == 0
    assert any(event.event_type == "run_retried" for event in retried.events)


def test_workflow_creation_is_idempotent_per_project(session) -> None:
    project = ProjectService(session).create(name="长安", genre="历史")
    service = WorkflowService(session)

    first = service.create_chapter_workflow(
        project.id,
        goal="进入长安",
        idempotency_key="chapter-001",
    )
    second = service.create_chapter_workflow(
        project.id,
        goal="该输入不会创建第二个任务",
        idempotency_key="chapter-001",
    )

    assert second.run.id == first.run.id
    assert len(service.list_for_project(project.id)) == 1


def test_expired_worker_lease_resumes_running_step(session) -> None:
    project = ProjectService(session).create(name="长安", genre="历史")
    service = WorkflowService(session)
    run_id = service.create_chapter_workflow(
        project.id,
        goal="进入长安",
    ).run.id

    first_claim = service.claim_next("worker-1", lease_seconds=300)
    assert first_claim is not None
    first_step = service.prepare_claimed_step(run_id, worker_id="worker-1")
    assert first_step is not None and first_step.attempt == 1

    expired = service.repositories.workflow_runs.require(run_id).model_copy(
        update={"claim_expires_at": utc_now() - timedelta(seconds=1)}
    )
    service.repositories.workflow_runs.update(expired)

    second_claim = service.claim_next("worker-2", lease_seconds=300)
    assert second_claim is not None
    resumed_step = service.prepare_claimed_step(run_id, worker_id="worker-2")

    assert resumed_step is not None
    assert resumed_step.name == first_step.name
    assert resumed_step.attempt == 2


def test_auto_approval_stops_when_research_has_no_verified_source(session) -> None:
    project = ProjectService(session).create(name="长安", genre="历史")
    service = WorkflowService(session)
    run_id = service.create_chapter_workflow(
        project.id,
        goal="进入长安",
        research_topic="汉代城门制度",
        auto_approve=True,
    ).run.id

    claimed = service.claim_next("worker-1")
    assert claimed is not None
    step = service.prepare_claimed_step(run_id, worker_id="worker-1")
    assert step is not None and step.name == "research"
    service.complete_step(
        run_id,
        "research",
        {
            "sources": [
                {
                    "url": "https://example.com",
                    "verification_status": "snippet_only",
                    "credibility_score": 0.9,
                }
            ]
        },
        worker_id="worker-1",
    )

    claimed = service.claim_next("worker-1")
    assert claimed is not None
    assert service.prepare_claimed_step(run_id, worker_id="worker-1") is None
    detail = service.detail(run_id)

    assert detail.run.status == "waiting_approval"
    assert detail.run.current_step == "research_approval"


@pytest.mark.asyncio
async def test_auto_approved_worker_completes_chapter_workflow(runtime) -> None:
    with session_scope(runtime.session_factory) as session:
        project = ProjectService(session).create(name="长安", genre="历史")
        run_id = (
            WorkflowService(session)
            .create_chapter_workflow(
                project.id,
                goal="主角通过城门查验",
                current="主角抵达城外",
                auto_approve=True,
            )
            .run.id
        )

    worker = WorkflowWorker(
        runtime,
        worker_id="test-worker",
        retry_backoff_seconds=0,
    )
    for _ in range(12):
        assert await worker.run_once()
        with session_scope(runtime.session_factory) as session:
            status = WorkflowService(session).detail(run_id).run.status
        if status == "succeeded":
            break

    with session_scope(runtime.session_factory) as session:
        detail = WorkflowService(session).detail(run_id)
        bible = StoryBibleService(session).get(project.id)

    assert detail.run.status == "succeeded"
    assert set(detail.run.result) == {
        "memory_preflight",
        "plan",
        "write",
        "quality_gate",
        "canon_commit",
        "memory_extract",
    }
    assert detail.run.result["write"]["draft_id"]
    assert detail.run.result["canon_commit"]["bible_version"] == 2
    assert detail.run.result["memory_extract"]["memory_count"] >= 1
    assert bible.version == 2
    assert all(step.status in {"succeeded", "skipped"} for step in detail.steps)
    assert [event.sequence for event in detail.events] == list(range(1, len(detail.events) + 1))
