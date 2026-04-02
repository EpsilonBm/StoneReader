"""Parse MOBI/AZW3 files into chapter items."""

from __future__ import annotations

from pathlib import Path
import re
import urllib.parse
import xml.etree.ElementTree as ET
import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from .text_chapters import ChapterItem, parse_txt


def _strip_html_to_text(content: bytes) -> str:
    soup = _parse_document(content)
    for bad in soup(["script", "style", "nav"]):
        bad.extract()
    text = soup.get_text(separator="\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join("　　" + line for line in lines)


def _extract_title_from_html(content: bytes) -> str:
    soup = _parse_document(content)
    for selector in ("h1", "h2", "h3", "title"):
        node = soup.select_one(selector)
        if node:
            text = node.get_text(" ", strip=True)
            if text:
                return text
    return ""


def _parse_document(content: bytes) -> BeautifulSoup:
    text = content.lstrip()[:120].lower()
    looks_xml = text.startswith(b"<?xml") or b"<ncx" in text or b"<package" in text
    if looks_xml:
        try:
            return BeautifulSoup(content, "xml")
        except Exception:
            pass
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
        return BeautifulSoup(content, "html.parser")


def _parse_toc_map(root: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    ncx_files = sorted(root.rglob("*.ncx"))
    if not ncx_files:
        return mapping
    try:
        data = ncx_files[0].read_bytes()
        xml = ET.fromstring(data)
        ns = xml.tag.split("}")[0] + "}" if "}" in xml.tag else ""
        for navpoint in xml.findall(f".//{ns}navPoint"):
            text_node = navpoint.find(f".//{ns}text")
            content_node = navpoint.find(f"{ns}content")
            if text_node is None or content_node is None:
                continue
            src = content_node.attrib.get("src", "")
            href = urllib.parse.unquote(src).split("#")[0]
            title = (text_node.text or "").strip()
            if href and title:
                mapping[Path(href).name.lower()] = title
    except Exception:
        return mapping
    return mapping


def parse_mobi(file_path: str) -> list[ChapterItem]:
    """Parse mobi/azw3 by unpacking and extracting HTML/TXT payload."""
    try:
        import mobi  # type: ignore
    except Exception:
        return [ChapterItem("解析失败", "未安装 mobi 依赖，无法解析 mobi/azw3。")]

    chapters: list[ChapterItem] = []

    try:
        extract_result = mobi.extract(file_path)
        unpack_root = extract_result[0] if isinstance(extract_result, tuple) else extract_result
        root = Path(unpack_root)
        toc_map = _parse_toc_map(root)

        html_files = sorted(
            [
                p
                for p in root.rglob("*")
                if p.suffix.lower() in {".html", ".htm", ".xhtml"}
            ]
        )

        if html_files:
            for p in html_files:
                raw = p.read_bytes()
                text = _strip_html_to_text(raw)
                if not text.strip():
                    continue
                title = toc_map.get(p.name.lower()) or _extract_title_from_html(raw)
                if not title:
                    if re.fullmatch(r"part\d+", p.stem.lower()):
                        title = f"章节 {len(chapters) + 1}"
                    else:
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

    if len(chapters) == 1:
        split = parse_txt(chapters[0].text)
        if len(split) > 1:
            chapters = split
        else:
            # Some mobi books lose explicit heading markers after conversion; split by size as fallback.
            text = chapters[0].text
            if len(text) > 30000:
                parts: list[ChapterItem] = []
                block = 25000
                cursor = 0
                idx = 1
                while cursor < len(text):
                    end = min(len(text), cursor + block)
                    if end < len(text):
                        pivot = text.rfind("\n", cursor + int(block * 0.7), end)
                        if pivot > cursor:
                            end = pivot
                    chunk = text[cursor:end].strip()
                    if chunk:
                        parts.append(ChapterItem(f"第{idx}节", chunk))
                        idx += 1
                    cursor = max(end + 1, cursor + 1)
                if len(parts) > 1:
                    chapters = parts

    if not chapters:
        return [ChapterItem("全文", "未提取到可阅读文本，可能为图片型电子书。")]
    return chapters
