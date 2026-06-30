"""Quality review queue over continuity, fact and memory findings."""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal, cast

from sqlalchemy.orm import Session

from novel_harness.models import (
    ContinuityIssue,
    FactRisk,
    MemoryConflict,
    QualityIssue,
    QualityIssueListResponse,
    QualityIssueSummary,
    WriteResponse,
    utc_now,
)
from novel_harness.storage.repositories import Repositories, ResourceNotFoundError

from .generation_service import GenerationService

IssueType = Literal["continuity", "fact", "memory"]
IssueStatus = Literal["open", "resolved", "ignored"]


class QualityReviewService:
    """Aggregate review findings into a single author-facing queue."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repositories = Repositories(session)

    def list_issues(
        self,
        project_id: str,
        *,
        issue_type: IssueType | None = None,
        status: IssueStatus | None = None,
        draft_id: str | None = None,
        chapter_id: str | None = None,
        limit: int = 200,
    ) -> QualityIssueListResponse:
        self.repositories.projects.require(project_id)
        collected: list[QualityIssue] = []
        if issue_type in (None, "continuity"):
            collected.extend(
                self._from_continuity(issue)
                for issue in self.repositories.continuity_issues.list_for_project(
                    project_id,
                    status=status,
                    limit=limit,
                )
            )
        if issue_type in (None, "fact"):
            collected.extend(
                self._from_fact(risk)
                for risk in self.repositories.fact_risks.list_for_project(
                    project_id,
                    status=status,
                    limit=limit,
                )
            )
        if issue_type in (None, "memory"):
            collected.extend(
                self._from_memory(conflict)
                for conflict in self.repositories.memory_conflicts.list_for_project(
                    project_id,
                    status=status,
                    limit=limit,
                )
            )
        if draft_id is not None:
            collected = [issue for issue in collected if issue.draft_id == draft_id]
        if chapter_id is not None:
            collected = [issue for issue in collected if issue.chapter_id == chapter_id]
        collected.sort(key=lambda issue: issue.created_at, reverse=True)
        collected = collected[:limit]
        return QualityIssueListResponse(
            issues=collected,
            summary=self._summary(collected),
        )

    def get_issue(self, issue_id: str) -> QualityIssue:
        source_type, source = self._find_source(issue_id)
        if source_type == "continuity":
            return self._from_continuity(cast(ContinuityIssue, source))
        if source_type == "fact":
            return self._from_fact(cast(FactRisk, source))
        return self._from_memory(cast(MemoryConflict, source))

    def update_issue(
        self,
        issue_id: str,
        *,
        status: IssueStatus | None = None,
        resolution_note: str | None = None,
    ) -> QualityIssue:
        source_type, source = self._find_source(issue_id)
        next_status: IssueStatus = status or source.status
        resolved_at = utc_now() if next_status in {"resolved", "ignored"} else None
        note = source.resolution_note if resolution_note is None else resolution_note.strip()
        updates = {
            "status": next_status,
            "resolution_note": note,
            "resolved_at": resolved_at,
        }
        if source_type == "continuity":
            continuity = cast(ContinuityIssue, source)
            updated_continuity = self.repositories.continuity_issues.update(
                continuity.model_copy(update=updates)
            )
            return self._from_continuity(updated_continuity)
        if source_type == "fact":
            risk = cast(FactRisk, source)
            updated_risk = self.repositories.fact_risks.update(risk.model_copy(update=updates))
            return self._from_fact(updated_risk)
        conflict = cast(MemoryConflict, source)
        updated_conflict = self.repositories.memory_conflicts.update(
            conflict.model_copy(update={**updates, "resolved": next_status != "open"})
        )
        return self._from_memory(updated_conflict)

    async def revise_from_issue(
        self,
        issue_id: str,
        generation_service: GenerationService,
        *,
        instruction: str | None = None,
    ) -> WriteResponse:
        issue = self.get_issue(issue_id)
        if issue.draft_id is None:
            raise ValueError("quality issue is not linked to a draft")
        revision_instruction = (
            instruction.strip() if instruction else self._revision_instruction(issue)
        )
        draft, issues, risks, originality, patch_id = await generation_service.revise_draft(
            issue.draft_id,
            instruction=revision_instruction,
        )
        return WriteResponse(
            draft=draft,
            continuity_issues=issues,
            fact_risks=risks,
            originality=asdict(originality),
            canon_patch_id=patch_id,
        )

    def _find_source(
        self,
        issue_id: str,
    ) -> tuple[IssueType, ContinuityIssue | FactRisk | MemoryConflict]:
        issue = self.repositories.continuity_issues.get(issue_id)
        if issue is not None:
            return "continuity", issue
        risk = self.repositories.fact_risks.get(issue_id)
        if risk is not None:
            return "fact", risk
        conflict = self.repositories.memory_conflicts.get(issue_id)
        if conflict is not None:
            return "memory", conflict
        raise ResourceNotFoundError(f"quality issue {issue_id!r} was not found")

    def _from_continuity(self, issue: ContinuityIssue) -> QualityIssue:
        chapter_id, chapter_title = self._chapter_context(issue.draft_id)
        return QualityIssue(
            id=issue.id,
            project_id=issue.project_id,
            issue_type="continuity",
            status=issue.status,
            severity=issue.severity,
            raw_level=issue.severity,
            category=issue.category,
            title=f"连续性问题：{issue.category}",
            description=issue.description,
            evidence=issue.evidence,
            suggestion=issue.suggestion,
            draft_id=issue.draft_id,
            chapter_id=chapter_id,
            chapter_title=chapter_title,
            resolution_note=issue.resolution_note,
            created_at=issue.created_at,
            updated_at=issue.updated_at,
            resolved_at=issue.resolved_at,
        )

    def _from_fact(self, risk: FactRisk) -> QualityIssue:
        chapter_id, chapter_title = self._chapter_context(risk.draft_id)
        return QualityIssue(
            id=risk.id,
            project_id=risk.project_id,
            issue_type="fact",
            status=risk.status,
            severity=_fact_severity(risk.risk_level),
            raw_level=risk.risk_level,
            category=risk.assessment,
            title=f"事实风险：{risk.claim[:80]}",
            description=risk.reason or risk.claim,
            evidence=risk.claim,
            suggestion=risk.suggestion,
            draft_id=risk.draft_id,
            chapter_id=chapter_id,
            chapter_title=chapter_title,
            source_urls=[str(url) for url in risk.source_urls],
            resolution_note=risk.resolution_note,
            created_at=risk.created_at,
            updated_at=risk.updated_at,
            resolved_at=risk.resolved_at,
        )

    def _from_memory(self, conflict: MemoryConflict) -> QualityIssue:
        status: IssueStatus = (
            "resolved" if conflict.resolved and conflict.status == "open" else conflict.status
        )
        return QualityIssue(
            id=conflict.id,
            project_id=conflict.project_id,
            issue_type="memory",
            status=status,
            severity="error" if conflict.severity == "hard" else "warning",
            raw_level=conflict.severity,
            category=conflict.category,
            title=f"长期记忆冲突：{conflict.category}",
            description=conflict.description,
            evidence=conflict.query,
            suggestion=conflict.suggestion,
            run_id=conflict.run_id,
            memory_ids=conflict.memory_ids,
            resolution_note=conflict.resolution_note,
            created_at=conflict.created_at,
            updated_at=conflict.updated_at,
            resolved_at=conflict.resolved_at,
        )

    def _chapter_context(self, draft_id: str | None) -> tuple[str | None, str | None]:
        if draft_id is None:
            return None, None
        draft = self.repositories.generations.get(draft_id)
        chapter = self.repositories.manuscript_chapters.get_by_draft(draft_id)
        if chapter is not None:
            return chapter.id, chapter.title
        return (draft.chapter_id if draft is not None else None), None

    @staticmethod
    def _summary(issues: list[QualityIssue]) -> QualityIssueSummary:
        by_status = {status: 0 for status in ("open", "resolved", "ignored")}
        by_severity = {severity: 0 for severity in ("error", "warning", "info")}
        for issue in issues:
            by_status[issue.status] += 1
            by_severity[issue.severity] += 1
        return QualityIssueSummary(
            total=len(issues),
            open=by_status["open"],
            resolved=by_status["resolved"],
            ignored=by_status["ignored"],
            error=by_severity["error"],
            warning=by_severity["warning"],
            info=by_severity["info"],
        )

    @staticmethod
    def _revision_instruction(issue: QualityIssue) -> str:
        parts = [
            "请根据以下审校问题修订章节草稿，保持原有风格和剧情意图。",
            f"问题类型：{issue.issue_type}",
            f"严重级别：{issue.raw_level or issue.severity}",
            f"问题描述：{issue.description}",
        ]
        if issue.evidence:
            parts.append(f"证据：{issue.evidence}")
        if issue.suggestion:
            parts.append(f"修改建议：{issue.suggestion}")
        return "\n".join(parts)


def _fact_severity(level: str) -> Literal["info", "warning", "error"]:
    if level in {"high", "unknown"}:
        return "error"
    if level == "medium":
        return "warning"
    return "info"
