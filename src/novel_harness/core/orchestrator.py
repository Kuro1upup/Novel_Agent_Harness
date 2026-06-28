"""High-level use-case facade for non-HTTP/non-CLI integrations."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from novel_harness.runtime import Runtime


class Orchestrator:
    """Expose the main workflow while keeping transaction boundaries explicit."""

    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime

    def create_project(self, **fields: Any) -> Any:
        from novel_harness.services import ProjectService
        from novel_harness.storage import session_scope

        with session_scope(self.runtime.session_factory) as session:
            return ProjectService(session).create(**fields)

    async def ingest_style(self, project_id: str, path: Path) -> Any:
        from novel_harness.storage import session_scope

        with session_scope(self.runtime.session_factory) as session:
            document, text = self.runtime.document_service(session).ingest_path(project_id, path)
            return await self.runtime.generation_service(session).analyze_style(
                project_id,
                text,
                source_document_ids=[document.id],
            )

    async def research(self, project_id: str, topic: str) -> Any:
        from novel_harness.storage import session_scope

        with session_scope(self.runtime.session_factory) as session:
            return await self.runtime.research_service(session).research(project_id, topic)

    async def plan(self, project_id: str, current: str, goal: str) -> Any:
        from novel_harness.storage import session_scope

        with session_scope(self.runtime.session_factory) as session:
            return await self.runtime.generation_service(session).plan(project_id, current, goal)

    async def write(self, project_id: str, goal: str, *, current: str = "") -> Any:
        from novel_harness.storage import session_scope

        with session_scope(self.runtime.session_factory) as session:
            return await self.runtime.generation_service(session).write(
                project_id, goal, current_summary=current
            )

    async def check(self, project_id: str, draft: str) -> Any:
        from novel_harness.storage import session_scope

        with session_scope(self.runtime.session_factory) as session:
            return await self.runtime.generation_service(session).check(project_id, draft)

    def accept_patch(self, patch_id: str) -> Any:
        from novel_harness.services import StoryBibleService
        from novel_harness.storage import session_scope

        with session_scope(self.runtime.session_factory) as session:
            return StoryBibleService(session).accept_patch(patch_id)
