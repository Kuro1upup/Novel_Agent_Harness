"""Author-controlled character, worldbuilding, and foreshadowing proposals."""

from __future__ import annotations

from sqlalchemy.orm import Session

from novel_harness.agents import CharacterAgent, ForeshadowingAgent, WorldbuildingAgent
from novel_harness.models import (
    CharacterProfile,
    ForeshadowingProposal,
    StoryBible,
    WorldbuildingProposal,
)
from novel_harness.storage.repositories import Repositories

from .agent_run_service import AgentRunService
from .story_bible_service import StoryBibleService


class CreativeService:
    def __init__(
        self,
        session: Session,
        *,
        character_agent: CharacterAgent,
        worldbuilding_agent: WorldbuildingAgent,
        foreshadowing_agent: ForeshadowingAgent,
        agent_runs: AgentRunService,
    ) -> None:
        self.repositories = Repositories(session)
        self.bible_service = StoryBibleService(session)
        self.character_agent = character_agent
        self.worldbuilding_agent = worldbuilding_agent
        self.foreshadowing_agent = foreshadowing_agent
        self.agent_runs = agent_runs

    async def propose_character(
        self,
        project_id: str,
        *,
        name: str,
        role: str = "",
        brief: str = "",
        apply: bool = False,
    ) -> tuple[CharacterProfile, StoryBible | None]:
        bible = self.bible_service.get(project_id)
        proposal: CharacterProfile = await self.agent_runs.execute(
            project_id,
            "character_agent",
            lambda: self.character_agent.run(
                name=name,
                role=role,
                brief=brief,
                story_bible=bible,
                project_id=project_id,
            ),
            input_summary=f"name={name[:100]};role={role[:100]}",
        )
        updated = self.bible_service.add_character(project_id, proposal) if apply else None
        return proposal, updated

    async def propose_worldbuilding(
        self,
        project_id: str,
        *,
        goal: str,
        apply: bool = False,
    ) -> tuple[WorldbuildingProposal, StoryBible | None]:
        project = self.repositories.projects.require(project_id)
        bible = self.bible_service.get(project_id)
        proposal: WorldbuildingProposal = await self.agent_runs.execute(
            project_id,
            "worldbuilding_agent",
            lambda: self.worldbuilding_agent.run(
                genre=project.genre,
                premise=project.premise,
                goal=goal,
                story_bible=bible,
            ),
            input_summary=f"goal_chars={len(goal)}",
        )
        updated = self.bible_service.apply_worldbuilding(project_id, proposal) if apply else None
        return proposal, updated

    async def propose_foreshadowing(
        self,
        project_id: str,
        *,
        scene_goal: str,
        max_actions: int = 3,
        apply: bool = False,
    ) -> tuple[ForeshadowingProposal, StoryBible | None]:
        bible = self.bible_service.get(project_id)
        proposal: ForeshadowingProposal = await self.agent_runs.execute(
            project_id,
            "foreshadowing_agent",
            lambda: self.foreshadowing_agent.run(
                bible,
                scene_goal,
                max_actions=max_actions,
            ),
            input_summary=f"scene_goal_chars={len(scene_goal)};max_actions={max_actions}",
        )
        updated = self.bible_service.apply_foreshadowing(project_id, proposal) if apply else None
        return proposal, updated
