import pytest

from novel_harness.agents import StyleAnalyzer
from novel_harness.models import StyleProfile


def test_style_analyzer_returns_profile() -> None:
    text = "夜色压下来。\n\n“快走！”林川回头说道。\n\n风像刀一样越过长街。"
    result = StyleAnalyzer().analyze([text, text], project_id="project-1")
    assert isinstance(result, StyleProfile)
    assert result.project_id == "project-1"
    assert result.sentence_length > 0
    assert 0 <= result.dialogue_ratio <= 1
    assert any("不复刻" in item for item in result.continuation_guidelines)


def test_style_analyzer_rejects_empty_input() -> None:
    with pytest.raises(ValueError):
        StyleAnalyzer().analyze([])
