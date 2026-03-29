"""Tests for plain text chapter detection."""

from stonereader.utils.text_chapters import detect_chapters


def test_detect_chapters_fallback_to_full_text() -> None:
    text = "line1\nline2\n"
    chapters = detect_chapters(text)

    assert len(chapters) == 1
    assert chapters[0].title == "全文"
    assert chapters[0].start == 0
    assert chapters[0].end == len(text)


def test_detect_chapters_with_chinese_titles() -> None:
    text = "前言\n\n第一章 起点\n内容A\n第二章 远行\n内容B\n"
    chapters = detect_chapters(text)

    assert len(chapters) == 2
    assert chapters[0].title.startswith("第一章")
    assert chapters[1].title.startswith("第二章")
    assert chapters[0].start < chapters[0].end <= chapters[1].start
