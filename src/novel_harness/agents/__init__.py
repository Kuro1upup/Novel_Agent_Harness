"""Composable agents used by the novel creation harness."""

from .character_agent import CharacterAgent
from .continuity_checker import ContinuityChecker
from .fact_checker import FactChecker
from .foreshadowing_agent import (
    ForeshadowingAction,
    ForeshadowingAgent,
    ForeshadowingProposal,
)
from .memory_extractor import MemoryExtractor
from .plot_planner import PlotPlanner
from .research_agent import ResearchAgent
from .revision_agent import RevisionAgent
from .scene_writer import SceneWriter
from .style_analyzer import StyleAnalyzer
from .worldbuilding_agent import WorldbuildingAgent, WorldbuildingProposal

__all__ = [
    "CharacterAgent",
    "ContinuityChecker",
    "FactChecker",
    "ForeshadowingAction",
    "ForeshadowingAgent",
    "ForeshadowingProposal",
    "MemoryExtractor",
    "PlotPlanner",
    "ResearchAgent",
    "RevisionAgent",
    "SceneWriter",
    "StyleAnalyzer",
    "WorldbuildingAgent",
    "WorldbuildingProposal",
]
