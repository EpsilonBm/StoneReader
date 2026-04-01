"""Parse MOBI/AZW3 files into chapter items."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from bs4 import BeautifulSoup

from .text_chapters import ChapterItem


def _strip_html_to_text(content: bytes) -> str:
    soup = BeautifulSoup(content, "html.parser")
    for bad in soup(["script", "style", "nav"]):
        bad.extract()
    text = soup.get_text(separator="\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join("　　" + line for line in lines)


def parse_mobi(file_path: str) -> list[ChapterItem]:
    """Parse mobi/azw3 by unpacking and extracting HTML/TXT payload."""
    try:
        import mobi  # type: ignore
    except Exception:
        return [ChapterItem("解析失败", "未安装 mobi 依赖，无法解析 mobi/azw3。")]

    tmp_dir = Path(tempfile.mkdtemp(prefix="stonereader_mobi_"))
    chapters: list[ChapterItem] = []

    try:
        unpack_root, _ = mobi.extract(file_path, str(tmp_dir))
        root = Path(unpack_root)

        html_files = sorted(
            [
                p
                for p in root.rglob("*")
                if p.suffix.lower() in {".html", ".htm", ".xhtml", ".xml"}
            ]
        )

        if html_files:
            for p in html_files:
                raw = p.read_bytes()
                text = _strip_html_to_text(raw)
                if not text.strip():
                    continue
                title = p.stem
                chapters.append(ChapterItem(title, text))

        if not chapters:
            txt_files = sorted([p for p in root.rglob("*") if p.suffix.lower() in {".txt"}])
            for p in txt_files:
                raw = p.read_text(encoding="utf-8", errors="ignore")
                lines = [line.strip() for line in raw.splitlines() if line.strip()]
                if not lines:
                    continue
                chapters.append(ChapterItem(p.stem, "\n".join("　　" + line for line in lines)))

    except Exception as exc:
        return [ChapterItem("解析失败", f"MOBI/AZW3 解析错误: {exc}")]
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if not chapters:
        return [ChapterItem("全文", "未提取到可阅读文本，可能为图片型电子书。")]
    return chapters
