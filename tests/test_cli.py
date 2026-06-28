import pytest
from typer.testing import CliRunner

from novel_harness.cli import _is_indexable_research_note, app


def test_cli_help_lists_required_commands() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in (
        "init",
        "ingest-style",
        "research",
        "bible",
        "plan",
        "write",
        "check",
        "workflow",
        "memory",
        "agent",
        "ops",
        "draft",
        "worker",
    ):
        assert command in result.stdout


@pytest.mark.parametrize(
    ("status", "credibility", "url", "expected"),
    [
        ("fetched", 0.8, "https://example.com/report", True),
        ("corroborated", 0.5, "https://example.com/report", True),
        ("snippet_only", 0.8, "https://example.com/report", False),
        ("fetched", 0.49, "https://example.com/report", False),
        ("corroborated", 0.9, "https://wappass.baidu.com/static/captcha/", False),
    ],
)
def test_research_rebuild_filter(
    status: str,
    credibility: float,
    url: str,
    expected: bool,
) -> None:
    assert (
        _is_indexable_research_note(
            verification_status=status,
            credibility_score=credibility,
            source_url=url,
        )
        is expected
    )
