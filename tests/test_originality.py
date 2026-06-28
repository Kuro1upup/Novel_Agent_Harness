from novel_harness.core import check_originality


def test_originality_blocks_long_verbatim_fragment() -> None:
    source = "城门在暮色中缓缓关闭，守卫举起长戟拦住最后一名旅人。"
    copied = f"开篇之后，{source}随后故事继续。"
    report = check_originality(copied, [source], max_contiguous_chars=12)
    assert not report.passed
    assert report.longest_contiguous_match >= len(source) - 2


def test_originality_allows_unrelated_text() -> None:
    report = check_originality(
        "雨水落在新修的石阶上，来客停下脚步。",
        ["荒原尽头升起了一轮苍白的太阳。"],
    )
    assert report.passed
