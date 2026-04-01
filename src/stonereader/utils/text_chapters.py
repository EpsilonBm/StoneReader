"""Text chapter parsing helpers for plain TXT content."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(slots=True)
class ChapterSpan:
    """Represents a chapter range in plain text."""

    title: str
    start: int
    end: int


@dataclass(slots=True)
class ChapterItem:
    """Represents a discrete chapter body and title."""

    title: str
    text: str


_CHAPTER_PATTERNS = [
    re.compile(r"^\s*第[零一二三四五六七八九十百千万0-9]+[章节回卷部篇集].*$"),
    re.compile(r"^\s*chapter\s+[0-9ivxlcdm]+.*$", flags=re.IGNORECASE),
]


def detect_chapters(text: str) -> list[ChapterSpan]:
    """Detect chapter spans from plain text.

    Falls back to one synthetic chapter when no heading is found.
    """
    if not text:
        return [ChapterSpan(title="全文", start=0, end=0)]

    starts: list[tuple[str, int]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        line_stripped = line.strip()
        if line_stripped and any(pattern.match(line_stripped) for pattern in _CHAPTER_PATTERNS):
            starts.append((line_stripped[:80], offset))
        offset += len(line)

    if not starts:
        return [ChapterSpan(title="全文", start=0, end=len(text))]

    spans: list[ChapterSpan] = []
    for idx, (title, start) in enumerate(starts):
        end = starts[idx + 1][1] if idx + 1 < len(starts) else len(text)
        spans.append(ChapterSpan(title=title, start=start, end=end))

    return spans
