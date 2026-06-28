"""Style, planning, drafting and review workflows."""

from __future__ import annotations

import difflib
import hashlib
from collections.abc import Sequence
from typing import Any

from sqlalchemy.orm import Session

from novel_harness.agents import (
    ContinuityChecker,
    FactChecker,
    PlotPlanner,
    RevisionAgent,
    SceneWriter,
    StyleAnalyzer,
)
from novel_harness.core.context_manager import (
    ContextManager,
    RetrievalContext,
)
from novel_harness.core.originality import OriginalityReport, check_originality
from novel_harness.exceptions import OriginalityError
from novel_harness.models import (
    ContextReference,
    ContinuityIssue,
    FactRisk,
    GenerationResult,
    PlotPlan,
    ResearchNote,
    StoryBible,
    StyleProfile,
)
from novel_harness.providers.embedding import EmbeddingProvider
from novel_harness.providers.vectorstore import VectorRecord, VectorStore
from novel_harness.storage.repositories import Repositories

from .agent_run_service import AgentRunService
from .story_bible_service import StoryBibleService


class GenerationService:
    def __init__(
        self,
        session: Session,
        *,
        object_store: Any,
        vector_store: VectorStore,
        embedding_provider: EmbeddingProvider,
        style_analyzer: StyleAnalyzer,
        plot_planner: PlotPlanner,
        scene_writer: SceneWriter,
        continuity_checker: ContinuityChecker,
        fact_checker: FactChecker,
        revision_agent: RevisionAgent,
        originality_max_contiguous_chars: int = 24,
        originality_max_ngram_overlap: float = 0.35,
        context_max_characters: int = 24_000,
        context_retrieval_limit: int = 12,
        agent_runs: AgentRunService | None = None,
    ) -> None:
        self.session = session
        self.repositories = Repositories(session)
        self.object_store = object_store
        self.vector_store = vector_store
        self.embedding_provider = embedding_provider
        self.style_analyzer = style_analyzer
        self.plot_planner = plot_planner
        self.scene_writer = scene_writer
        self.continuity_checker = continuity_checker
        self.fact_checker = fact_checker
        self.revision_agent = revision_agent
        self.max_contiguous = originality_max_contiguous_chars
        self.max_ngram_overlap = originality_max_ngram_overlap
        self.context_max_characters = context_max_characters
        self.context_retrieval_limit = context_retrieval_limit
        self.agent_runs = agent_runs

    async def analyze_style(
        self,
        project_id: str,
        texts: str | Sequence[str],
        *,
        source_document_ids: Sequence[str] = (),
    ) -> StyleProfile:
        self.repositories.projects.require(project_id)

        async def operation() -> StyleProfile:
            return await self.style_analyzer.run(texts, project_id=project_id)

        character_count = len(texts) if isinstance(texts, str) else sum(len(item) for item in texts)
        profile = await self._run_agent(
            project_id,
            "style_analyzer",
            operation,
            input_summary=(
                f"documents={len(texts) if not isinstance(texts, str) else 1};"
                f"characters={character_count}"
            ),
        )
        previous = self.repositories.styles.list(project_id)
        profile = profile.model_copy(
            update={
                "version": len(previous) + 1,
                "source_document_ids": list(source_document_ids),
            }
        )
        self.repositories.styles.add(profile)
        return profile

    async def plan(
        self,
        project_id: str,
        current_summary: str,
        author_goal: str,
        *,
        retrieved_context: str | None = None,
        workflow_run_id: str | None = None,
    ) -> PlotPlan:
        bible = StoryBibleService(self.session).get(project_id)
        styles = self.repositories.styles.list(project_id)
        style = styles[-1] if styles else StyleProfile(project_id=project_id)
        if retrieved_context is None:
            retrieved_context, _ = self._rag_context(
                project_id,
                query=f"{author_goal}\n{current_summary}",
                bible=bible,
                style=style,
                current_summary=current_summary,
            )
        plan = await self._run_agent(
            project_id,
            "plot_planner",
            lambda: self.plot_planner.run(
                bible,
                current_summary,
                author_goal,
                project_id=project_id,
                retrieved_context=retrieved_context,
            ),
            input_summary=(
                f"goal_chars={len(author_goal)};summary_chars={len(current_summary)};"
                f"bible_version={bible.version}"
            ),
            workflow_run_id=workflow_run_id,
        )
        options = [
            option.model_copy(update={"plot_plan_id": plan.id})
            if not isinstance(option, dict)
            else option
            for option in plan.next_chapter_options
        ]
        plan = plan.model_copy(update={"next_chapter_options": options})
        self.repositories.plot_plans.add(plan)
        for option in plan.next_chapter_options:
            if isinstance(option, dict):
                continue
            self.repositories.plot_options.add(option)
        return plan

    async def write(
        self,
        project_id: str,
        scene_goal: str,
        *,
        current_summary: str = "",
        plot_plan: PlotPlan | None = None,
        selected_option_id: str | None = None,
        workflow_run_id: str | None = None,
    ) -> tuple[
        GenerationResult,
        list[ContinuityIssue],
        list[FactRisk],
        OriginalityReport,
        str,
    ]:
        self.repositories.projects.require(project_id)
        bible = StoryBibleService(self.session).get(project_id)
        styles = self.repositories.styles.list(project_id)
        style = styles[-1] if styles else StyleProfile(project_id=project_id)
        research = self.repositories.research.list(project_id, limit=100)
        retrieved_context, retrieval = self._rag_context(
            project_id,
            query=f"{scene_goal}\n{current_summary}",
            bible=bible,
            style=style,
            current_summary=current_summary,
        )
        relevant_research = self._relevant_research(retrieval, research)
        if plot_plan is not None and plot_plan.project_id != project_id:
            raise ValueError("plot plan belongs to another project")
        plan = plot_plan or await self.plan(
            project_id,
            current_summary or "当前章节之后",
            scene_goal,
            retrieved_context=retrieved_context,
            workflow_run_id=workflow_run_id,
        )
        if selected_option_id:
            plan = self.select_plot_option(project_id, plan.id, selected_option_id)
        plan = self._selected_plan(plan)
        draft = await self._run_agent(
            project_id,
            "scene_writer",
            lambda: self.scene_writer.run(
                style,
                bible,
                plan,
                relevant_research,
                scene_goal,
                project_id=project_id,
                retrieved_context=retrieved_context,
            ),
            input_summary=(
                f"goal_chars={len(scene_goal)};plan_id={plan.id};"
                f"selected_option_id={plan.selected_option_id or ''}"
            ),
            workflow_run_id=workflow_run_id,
        )
        draft = draft.model_copy(
            update={
                "plot_plan_id": plan.id,
                "selected_option_id": plan.selected_option_id,
                "retrieval_query": retrieval.query,
                "context_sources": self._context_references(project_id, retrieval),
            }
        )
        continuity = await self._run_agent(
            project_id,
            "continuity_checker",
            lambda: self.continuity_checker.run(draft.body, bible, project_id=project_id),
            input_summary=f"draft_chars={len(draft.body)};bible_version={bible.version}",
            workflow_run_id=workflow_run_id,
        )
        fact_risks = await self._run_agent(
            project_id,
            "fact_checker",
            lambda: self.fact_checker.run(draft.body, relevant_research, project_id=project_id),
            input_summary=(
                f"draft_chars={len(draft.body)};research_notes={len(relevant_research)}"
            ),
            workflow_run_id=workflow_run_id,
        )
        if any(issue.severity == "error" for issue in continuity) or any(
            risk.risk_level in {"high", "unknown"} for risk in fact_risks
        ):
            draft = await self._run_agent(
                project_id,
                "revision_agent",
                lambda: self.revision_agent.run(
                    draft, continuity, fact_risks, project_id=project_id
                ),
                input_summary=(
                    f"draft_id={draft.id};continuity={len(continuity)};fact_risks={len(fact_risks)}"
                ),
                workflow_run_id=workflow_run_id,
            )
            continuity = await self._run_agent(
                project_id,
                "continuity_checker",
                lambda: self.continuity_checker.run(draft.body, bible, project_id=project_id),
                input_summary=f"revision=true;draft_chars={len(draft.body)}",
                workflow_run_id=workflow_run_id,
            )
        draft = draft.model_copy(
            update={
                "retrieval_query": retrieval.query,
                "context_sources": self._context_references(project_id, retrieval),
                "plot_plan_id": plan.id,
                "selected_option_id": plan.selected_option_id,
            }
        )
        sources = self._source_texts(project_id)
        originality = check_originality(
            draft.body[:50_000],
            sources,
            max_contiguous_chars=self.max_contiguous,
            max_ngram_overlap=self.max_ngram_overlap,
        )
        if not originality.passed:
            raise OriginalityError(
                "draft overlaps an ingested source beyond the configured threshold"
            )

        digest = hashlib.sha256(draft.body.encode()).hexdigest()
        object_key = f"projects/{project_id}/drafts/{draft.id}/{digest}.md"
        self.object_store.put_bytes(
            object_key,
            draft.body.encode("utf-8"),
            content_type="text/markdown; charset=utf-8",
        )
        stored = draft.model_copy(update={"object_key": object_key})
        try:
            self.repositories.generations.add(stored)
            for issue in continuity:
                self.repositories.continuity_issues.add(
                    issue.model_copy(update={"draft_id": stored.id})
                )
            for risk in fact_risks:
                self.repositories.fact_risks.add(risk.model_copy(update={"draft_id": stored.id}))
            patch = StoryBibleService(self.session).create_patch(
                project_id,
                stored.id,
                [
                    {
                        "op": "add_canon_event",
                        "value": {
                            "draft_id": stored.id,
                            "summary": scene_goal,
                            "status": "accepted_draft",
                        },
                    }
                ],
            )
        except Exception:
            self.object_store.remove(object_key)
            raise
        return stored, continuity, fact_risks, originality, patch.id

    async def check(
        self,
        project_id: str,
        draft: str,
        *,
        research_notes: Sequence[ResearchNote] | None = None,
    ) -> tuple[list[ContinuityIssue], list[FactRisk]]:
        bible = StoryBibleService(self.session).get(project_id)
        notes = list(research_notes or self.repositories.research.list(project_id))
        continuity = await self._run_agent(
            project_id,
            "continuity_checker",
            lambda: self.continuity_checker.run(draft, bible, project_id=project_id),
            input_summary=f"standalone_check=true;draft_chars={len(draft)}",
        )
        fact_risks = await self._run_agent(
            project_id,
            "fact_checker",
            lambda: self.fact_checker.run(draft, notes, project_id=project_id),
            input_summary=f"standalone_check=true;research_notes={len(notes)}",
        )
        return continuity, fact_risks

    def get_draft(self, draft_id: str) -> GenerationResult:
        draft = self.repositories.generations.require(draft_id)
        if draft.object_key:
            body = self.object_store.get_bytes(draft.object_key).decode("utf-8")
            return draft.model_copy(update={"body": body})
        return draft

    def list_drafts(
        self,
        project_id: str,
        *,
        status: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[GenerationResult]:
        self.repositories.projects.require(project_id)
        return self.repositories.generations.list_by_status(
            project_id,
            status=status,
            offset=offset,
            limit=limit,
        )

    def select_plot_option(
        self,
        project_id: str,
        plot_plan_id: str,
        option_id: str,
    ) -> PlotPlan:
        plan = self.repositories.plot_plans.require(plot_plan_id)
        if plan.project_id != project_id:
            raise ValueError("plot plan belongs to another project")
        option = self.repositories.plot_options.require(option_id)
        if option.project_id != project_id or option.plot_plan_id != plot_plan_id:
            raise ValueError("plot option does not belong to this plan")
        return self.repositories.plot_plans.update(
            plan.model_copy(update={"selected_option_id": option_id})
        )

    def reject_draft(self, draft_id: str, *, reason: str) -> GenerationResult:
        draft = self.repositories.generations.require(draft_id)
        if draft.status == "accepted":
            raise ValueError("accepted drafts cannot be rejected")
        if draft.status == "rejected":
            return draft
        rejected = self.repositories.generations.update(
            draft.model_copy(
                update={
                    "status": "rejected",
                    "revision_instruction": reason.strip(),
                }
            )
        )
        patch = self.repositories.canon_patches.get_by_draft(draft_id)
        if patch is not None and patch.status == "pending":
            StoryBibleService(self.session).reject_patch(patch.id, reason=reason)
        return rejected

    async def revise_draft(
        self,
        draft_id: str,
        *,
        instruction: str,
        workflow_run_id: str | None = None,
    ) -> tuple[GenerationResult, list[ContinuityIssue], list[FactRisk], OriginalityReport, str]:
        if not instruction.strip():
            raise ValueError("revision instruction is required")
        original = self.get_draft(draft_id)
        if original.status == "accepted":
            raise ValueError("accepted drafts are immutable")
        bible = StoryBibleService(self.session).get(original.project_id)
        issues = self.repositories.continuity_issues.list_for_draft(draft_id)
        risks = self.repositories.fact_risks.list_for_draft(draft_id)
        revised = await self._run_agent(
            original.project_id,
            "revision_agent",
            lambda: self.revision_agent.run(
                original,
                issues,
                risks,
                project_id=original.project_id,
                author_feedback=instruction,
            ),
            input_summary=(
                f"parent_draft_id={draft_id};instruction_chars={len(instruction)};"
                f"revision={original.revision_number + 1}"
            ),
            workflow_run_id=workflow_run_id,
        )
        revised = revised.model_copy(
            update={
                "status": "draft",
                "object_key": None,
                "plot_plan_id": original.plot_plan_id,
                "selected_option_id": original.selected_option_id,
                "parent_draft_id": original.id,
                "revision_number": original.revision_number + 1,
                "revision_instruction": instruction.strip(),
                "retrieval_query": original.retrieval_query,
                "context_sources": original.context_sources,
                "bible_version": original.bible_version,
            }
        )
        continuity = await self._run_agent(
            original.project_id,
            "continuity_checker",
            lambda: self.continuity_checker.run(
                revised.body, bible, project_id=original.project_id
            ),
            input_summary=f"author_revision=true;draft_chars={len(revised.body)}",
            workflow_run_id=workflow_run_id,
        )
        research = self.repositories.research.list(original.project_id, limit=100)
        fact_risks = await self._run_agent(
            original.project_id,
            "fact_checker",
            lambda: self.fact_checker.run(revised.body, research, project_id=original.project_id),
            input_summary=f"author_revision=true;research_notes={len(research)}",
            workflow_run_id=workflow_run_id,
        )
        originality = check_originality(
            revised.body[:50_000],
            self._source_texts(original.project_id),
            max_contiguous_chars=self.max_contiguous,
            max_ngram_overlap=self.max_ngram_overlap,
        )
        if not originality.passed:
            raise OriginalityError(
                "revised draft overlaps an ingested source beyond the configured threshold"
            )
        digest = hashlib.sha256(revised.body.encode()).hexdigest()
        object_key = f"projects/{original.project_id}/drafts/{revised.id}/{digest}.md"
        self.object_store.put_bytes(
            object_key,
            revised.body.encode("utf-8"),
            content_type="text/markdown; charset=utf-8",
        )
        stored = revised.model_copy(update={"object_key": object_key})
        try:
            self.repositories.generations.add(stored)
            for issue in continuity:
                self.repositories.continuity_issues.add(
                    issue.model_copy(update={"draft_id": stored.id})
                )
            for risk in fact_risks:
                self.repositories.fact_risks.add(risk.model_copy(update={"draft_id": stored.id}))
            patch = StoryBibleService(self.session).create_patch(
                original.project_id,
                stored.id,
                [
                    {
                        "op": "add_canon_event",
                        "value": {
                            "draft_id": stored.id,
                            "summary": instruction.strip(),
                            "status": "accepted_revision",
                            "parent_draft_id": original.id,
                        },
                    }
                ],
            )
            if original.status == "draft":
                self.repositories.generations.update(
                    original.model_copy(update={"status": "superseded"})
                )
            old_patch = self.repositories.canon_patches.get_by_draft(original.id)
            if old_patch is not None and old_patch.status == "pending":
                StoryBibleService(self.session).reject_patch(
                    old_patch.id,
                    reason=f"superseded by revision {stored.id}",
                )
        except Exception:
            self.object_store.remove(object_key)
            raise
        return stored, continuity, fact_risks, originality, patch.id

    def compare_drafts(self, from_draft_id: str, to_draft_id: str) -> str:
        before = self.get_draft(from_draft_id)
        after = self.get_draft(to_draft_id)
        if before.project_id != after.project_id:
            raise ValueError("drafts belong to different projects")
        return "".join(
            difflib.unified_diff(
                before.body.splitlines(keepends=True),
                after.body.splitlines(keepends=True),
                fromfile=f"draft/{before.id}",
                tofile=f"draft/{after.id}",
            )
        )

    def _selected_plan(self, plan: PlotPlan) -> PlotPlan:
        if not plan.selected_option_id:
            return plan
        option = self.repositories.plot_options.require(plan.selected_option_id)
        if option.plot_plan_id != plan.id:
            raise ValueError("selected plot option does not belong to this plan")
        turning_points = list(plan.turning_points)
        if option.summary and option.summary not in turning_points:
            turning_points.append(option.summary)
        return plan.model_copy(
            update={
                "conflict": option.conflict or plan.conflict,
                "stakes": option.payoff or plan.stakes,
                "turning_points": turning_points,
                "foreshadowing_to_plant": list(
                    dict.fromkeys([*plan.foreshadowing_to_plant, *option.foreshadowing])
                ),
            }
        )

    async def _run_agent(
        self,
        project_id: str,
        agent_name: str,
        operation: Any,
        *,
        input_summary: str,
        workflow_run_id: str | None = None,
    ) -> Any:
        if self.agent_runs is None:
            return await operation()
        return await self.agent_runs.execute(
            project_id,
            agent_name,
            operation,
            input_summary=input_summary,
            workflow_run_id=workflow_run_id,
        )

    def _source_texts(self, project_id: str) -> list[str]:
        texts: list[str] = []
        for document in self.repositories.documents.list(project_id, limit=100):
            if not document.parsed_object_key or document.status != "ready":
                continue
            try:
                value = self.object_store.get_bytes(document.parsed_object_key)
                texts.append(value.decode("utf-8")[:50_000])
            except Exception:
                continue
        return texts

    def _rag_context(
        self,
        project_id: str,
        *,
        query: str,
        bible: StoryBible,
        style: StyleProfile,
        current_summary: str,
    ) -> tuple[str, RetrievalContext]:
        self._index_structured_context(project_id, bible=bible, style=style)
        manager = ContextManager(
            self.context_max_characters,
            vector_store=self.vector_store,
            embedding_provider=self.embedding_provider,
            object_store=self.object_store,
            repositories=self.repositories,
        )
        retrieval = manager.retrieve(
            project_id,
            query,
            source_types=[
                "story_bible",
                "character",
                "style",
                "memory",
                "research",
                "chapter",
                "document",
            ],
            limit=self.context_retrieval_limit,
        )
        grouped = retrieval.sections()
        sections: dict[str, str | list[str]] = {
            "story_bible": bible.model_dump_json(),
            "current_story": current_summary,
            "characters": [character.model_dump_json() for character in bible.characters],
            "style": style.model_dump_json(),
            "memory": grouped.get("memory", []),
            "research": grouped.get("research", []),
            "documents": grouped.get("document", []),
            "chapters": grouped.get("chapter", []),
            "retrieved_canon": [
                *grouped.get("story_bible", []),
                *grouped.get("character", []),
            ],
        }
        return manager.assemble(sections), retrieval

    def _index_structured_context(
        self, project_id: str, *, bible: StoryBible, style: StyleProfile
    ) -> None:
        rows: list[tuple[str, str, str, str, int, str]] = []

        def add(
            record_id: str,
            source_id: str,
            source_type: str,
            text: str,
            ordinal: int = 0,
        ) -> None:
            if not text.strip():
                return
            rows.append(
                (
                    record_id,
                    source_id,
                    source_type,
                    text,
                    ordinal,
                    hashlib.sha256(text.encode("utf-8")).hexdigest(),
                )
            )

        add(
            f"bible:{bible.id}",
            bible.id,
            "story_bible",
            bible.model_dump_json(),
        )
        for character in bible.characters:
            add(
                f"character:{character.id}",
                character.id,
                "character",
                character.model_dump_json(),
            )
        add(f"style:{style.id}", style.id, "style", style.model_dump_json())
        for draft in self.repositories.generations.list(project_id, limit=50):
            summary = "\n".join(
                part
                for part in (
                    draft.creative_notes,
                    draft.factual_basis_summary,
                )
                if part
            )
            add(f"chapter:{draft.id}", draft.id, "chapter", summary)
        if not rows:
            return
        vectors = self.embedding_provider.embed_documents([row[3][:6000] for row in rows])
        records = [
            VectorRecord(
                id=record_id,
                project_id=project_id,
                source_id=source_id,
                source_type=source_type,
                chunk_ordinal=ordinal,
                content_hash=content_hash,
                embedding=vector,
                metadata={"preview": text[:1200]},
            )
            for (
                record_id,
                source_id,
                source_type,
                text,
                ordinal,
                content_hash,
            ), vector in zip(rows, vectors, strict=True)
        ]
        self.vector_store.upsert(records)

    def _relevant_research(
        self,
        retrieval: RetrievalContext,
        all_notes: list[ResearchNote],
    ) -> list[ResearchNote]:
        selected_ids = {
            fragment.source_id
            for fragment in retrieval.fragments
            if fragment.source_type == "research"
        }
        selected = [note for note in all_notes if note.id in selected_ids]
        if selected:
            return selected
        return [
            note
            for note in all_notes
            if note.verification_status in {"fetched", "corroborated"}
            and note.credibility_score >= 0.5
        ][:10]

    @staticmethod
    def _context_references(project_id: str, retrieval: RetrievalContext) -> list[ContextReference]:
        references: list[ContextReference] = []
        for fragment in retrieval.fragments:
            source_url = fragment.metadata.get("source_url")
            references.append(
                ContextReference(
                    project_id=project_id,
                    source_id=fragment.source_id,
                    source_type=fragment.source_type,
                    score=fragment.score,
                    source_url=(str(source_url) if source_url is not None else None),
                    content_hash=fragment.content_hash,
                )
            )
        return references
