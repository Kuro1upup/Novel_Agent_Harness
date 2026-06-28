import hashlib

from novel_harness.agents import FactChecker
from novel_harness.models import EvidenceSnippet, ResearchNote


def test_fact_checker_marks_unsupported_claim_unknown() -> None:
    risks = FactChecker().check(
        "公元前二百年，这条法律规定所有商人必须缴纳三成税。",
        [],
        project_id="project-1",
    )
    assert risks
    assert risks[0].risk_level == "unknown"
    assert risks[0].assessment == "不确定"
    assert "二次搜索" in risks[0].suggestion


def test_fact_checker_uses_corroborated_evidence() -> None:
    text = "汉长安城礼制规定部分城门采用一门三道形制。"
    note = ResearchNote(
        project_id="project-1",
        topic="城门",
        query="汉长安城门",
        source_title="考古报告",
        source_url="https://history.example/report",
        credibility_score=0.8,
        verification_status="corroborated",
        evidence_snippets=[
            EvidenceSnippet(
                text=text,
                source_url="https://history.example/report",
                content_hash=hashlib.sha256(text.encode()).hexdigest(),
            )
        ],
    )
    risks = FactChecker().check(
        "汉长安城礼制规定部分城门采用一门三道形制。",
        [note],
        project_id="project-1",
    )
    assert risks[0].assessment == "确定"
    assert risks[0].source_urls
