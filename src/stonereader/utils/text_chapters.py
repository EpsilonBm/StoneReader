"""Text chapter parsing helpers for plain TXT content."""

from __future__ import annotations

from dataclasses import dataclass, field
import re

@dataclass(slots=True)
class ChapterSpan:
    title: str
    start: int
    end: int

@dataclass(slots=True)
class ChapterItem:
    title: str
    text: str
    footnotes: dict[str, str] = field(default_factory=dict)
    media: list[dict] = field(default_factory=list)
    inline_styles: list[dict] = field(default_factory=list)

_CHAPTER_PATTERNS = [
    re.compile(r"^\s*第[零一二三四五六七八九十百千万0-9]+[章节回卷部篇集].*$"),
    re.compile(r"^\s*chapter\s+[0-9ivxlcdm]+.*$", flags=re.IGNORECASE),
]

def parse_txt(text: str) -> list[ChapterItem]:
    spans = detect_chapters(text)
    items = []
    if not spans:
        return [ChapterItem("全文", text)]
    for span in spans:
        items.append(ChapterItem(span.title, text[span.start:span.end]))
    return items

def detect_chapters(text: str) -> list[ChapterSpan]:
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
