"""Parse MOBI/AZW3 files into chapter items."""

from __future__ import annotations

from pathlib import Path
import re
import urllib.parse
import xml.etree.ElementTree as ET
import warnings
import base64
import mimetypes

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from .text_chapters import ChapterItem, parse_txt


_BLOCK_TAGS = {
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "blockquote",
    "pre",
}

_INLINE_STYLE_RULES = {
    "bold": {"b", "strong"},
    "italic": {"i", "em"},
    "small": {"small", "sup", "sub"},
}

_NOTE_HINT_RE = re.compile(r"note|foot|fn|endnote|annotation|注", flags=re.IGNORECASE)


def _normalize_whitespace(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_node_text(node) -> str:
    if node is None:
        return ""
    return _normalize_whitespace(node.get_text(separator=" ", strip=True))


def _parse_css_declarations(css_text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for chunk in css_text.split(";"):
        if ":" not in chunk:
            continue
        k, v = chunk.split(":", 1)
        key = k.strip().lower()
        val = v.strip().lower()
        if key and val:
            result[key] = val
    return result


def _collect_class_style_map(soup: BeautifulSoup) -> dict[str, dict[str, str]]:
    class_style_map: dict[str, dict[str, str]] = {}
    for style_tag in soup.find_all("style"):
        css_text = style_tag.get_text("\n", strip=True)
        for selector, body in re.findall(r"([^{}]+)\{([^{}]+)\}", css_text):
            decls = _parse_css_declarations(body)
            if not decls:
                continue
            for cls_name in re.findall(r"\.([A-Za-z0-9_-]+)", selector):
                merged = dict(class_style_map.get(cls_name, {}))
                merged.update(decls)
                class_style_map[cls_name] = merged
    return class_style_map


def _merge_style_flags_from_css(flags: dict, decls: dict[str, str]) -> None:
    fw = decls.get("font-weight", "")
    if fw in {"bold", "bolder", "600", "700", "800", "900"}:
        flags["bold"] = True

    fs = decls.get("font-style", "")
    if fs in {"italic", "oblique"}:
        flags["italic"] = True

    td = decls.get("text-decoration", "")
    if "underline" in td:
        flags["underline"] = True
    if "line-through" in td:
        flags["strike"] = True

    color = decls.get("color", "")
    if color and color not in {"inherit", "initial", "unset"}:
        flags["color"] = color

    bg = decls.get("background-color", "") or decls.get("background", "")
    if bg and bg not in {"inherit", "initial", "unset", "none", "transparent"}:
        flags["background"] = bg

    size = decls.get("font-size", "")
    if size.endswith("%"):
        try:
            pct = float(size[:-1])
            if pct > 0:
                flags["size_factor"] = max(0.5, min(2.0, pct / 100.0))
        except ValueError:
            pass
    elif size in {"xx-small", "x-small", "small"}:
        flags["size_factor"] = 0.85
    elif size in {"large", "x-large", "xx-large"}:
        flags["size_factor"] = 1.15


def _style_flags_from_tag(tag, class_style_map: dict[str, dict[str, str]]) -> dict:
    flags: dict = {}
    name = str(getattr(tag, "name", "") or "").lower()

    if name in {"b", "strong"}:
        flags["bold"] = True
    if name in {"i", "em", "cite", "dfn", "var"}:
        flags["italic"] = True
    if name in {"u", "ins"}:
        flags["underline"] = True
    if name in {"s", "strike", "del"}:
        flags["strike"] = True
    if name in {"small", "sup", "sub"}:
        flags["size_factor"] = 0.85
    if name == "big":
        flags["size_factor"] = 1.15
    if name in {"code", "kbd", "samp", "tt"}:
        flags["monospace"] = True
    if name in {"mark"}:
        flags["background"] = "#fff59d"

    cls = tag.get("class", []) or []
    for c in cls:
        class_decls = class_style_map.get(str(c), {})
        if class_decls:
            _merge_style_flags_from_css(flags, class_decls)

    style_attr = str(tag.get("style", "") or "").strip()
    if style_attr:
        _merge_style_flags_from_css(flags, _parse_css_declarations(style_attr))

    return flags


def _collect_mobi_footnotes(soup: BeautifulSoup) -> dict[str, str]:
    footnotes: dict[str, str] = {}
    target_token_map: dict[str, str] = {}
    seq = 1

    id_nodes: dict[str, object] = {}
    for n in soup.find_all(attrs={"id": True}):
        nid = str(n.get("id", "")).strip()
        if nid:
            id_nodes[nid] = n

    for a in soup.find_all("a", href=True):
        href = str(a.get("href", "")).strip()
        if "#" not in href:
            continue
        target_id = href.split("#", 1)[1].strip()
        if not target_id:
            continue
        label = _extract_node_text(a)
        m = re.search(r"(\d{1,4})", label)
        note_hint = bool(
            _NOTE_HINT_RE.search(href)
            or _NOTE_HINT_RE.search(target_id)
            or _NOTE_HINT_RE.search(label)
            or getattr(a.parent, "name", "") in {"sup", "sub"}
        )
        if not m and not note_hint:
            continue

        if target_id in target_token_map:
            token = target_token_map[target_id]
        elif m:
            token = f"[{m.group(1)}]"
            target_token_map[target_id] = token
        else:
            token = f"[{seq}]"
            target_token_map[target_id] = token
            seq += 1

        num = token.strip("[]")
        try:
            a.clear()
            a.append(token)
        except Exception:
            pass

        target_node = id_nodes.get(target_id)
        note_node = target_node
        if getattr(target_node, "name", "") == "a" and getattr(target_node, "parent", None) is not None:
            note_node = target_node.parent

        note_text = _extract_node_text(note_node)
        if not note_text:
            continue
        note_text = re.sub(r"^\[?\s*(?:注\s*)?\d{1,4}\s*\]?\s*", "", note_text).strip()
        if not note_text:
            continue
        footnotes[token] = note_text
        footnotes[num] = note_text

    return footnotes


def _iter_meaningful_blocks(soup: BeautifulSoup):
    body = soup.body or soup
    for node in body.descendants:
        name = getattr(node, "name", None)
        if name not in _BLOCK_TAGS:
            continue
        parent = node.parent
        nested = False
        while parent is not None and parent is not body:
            if getattr(parent, "name", None) in _BLOCK_TAGS:
                nested = True
                break
            parent = parent.parent
        if not nested:
            yield node


def _block_to_paragraph_text(node) -> str:
    text = _normalize_whitespace(node.get_text(separator=" ", strip=True))
    if not text:
        return ""
    if getattr(node, "name", "") == "li":
        return f"• {text}"
    return text


def _collect_block_inline_styles(block_text: str, block, class_style_map: dict[str, dict[str, str]]) -> list[dict]:
    if not block_text:
        return []
    styles: list[dict] = []
    cursor = 0
    for tag in block.find_all(True):
        flags = _style_flags_from_tag(tag, class_style_map)
        if not flags:
            continue
        frag = _normalize_whitespace(tag.get_text(separator=" ", strip=True))
        if not frag:
            continue
        pos = block_text.find(frag, cursor)
        if pos < 0:
            pos = block_text.find(frag)
        if pos < 0:
            continue
        span: dict = {"start": pos, "end": pos + len(frag)}
        span.update(flags)
        styles.append(span)
        cursor = pos + len(frag)
    return styles


def _collect_paragraphs_and_styles(soup: BeautifulSoup, class_style_map: dict[str, dict[str, str]]) -> tuple[list[str], list[dict]]:
    paragraphs: list[str] = []
    paragraph_styles: list[list[dict]] = []
    for block in _iter_meaningful_blocks(soup):
        p_text = _block_to_paragraph_text(block)
        if not p_text:
            continue
        paragraphs.append(p_text)
        paragraph_styles.append(_collect_block_inline_styles(p_text, block, class_style_map))

    chapter_styles: list[dict] = []
    cursor = 0
    for idx, p in enumerate(paragraphs):
        for span in paragraph_styles[idx]:
            start = int(span.get("start", 0))
            end = int(span.get("end", start))
            if end <= start:
                continue
            mapped = dict(span)
            mapped["start"] = cursor + start
            mapped["end"] = cursor + end
            chapter_styles.append(mapped)
        cursor += len(p)
        if idx < len(paragraphs) - 1:
            cursor += 2

    return paragraphs, chapter_styles


def _extract_html_payload(content: bytes, html_path: Path) -> tuple[str, list[dict], dict[str, str], list[dict]]:
    soup = _parse_document(content)
    class_style_map = _collect_class_style_map(soup)
    for bad in soup(["script", "style", "nav"]):
        bad.extract()

    footnotes = _collect_mobi_footnotes(soup)

    media: list[dict] = []
    for img in soup.find_all("img"):
        src = str(img.get("src", "")).strip()
        alt = str(img.get("alt", "")).strip()
        if not src and not alt:
            continue

        token = f"[图{len(media) + 1}]"
        entry = {"type": "image", "token": token, "src": src, "alt": alt}

        src_clean = urllib.parse.unquote(src).split("#", 1)[0].split("?", 1)[0]
        if src_clean.lower().startswith("data:") and ";base64," in src_clean:
            entry["data_url"] = src_clean
        elif src_clean and not src_clean.lower().startswith(("http://", "https://")):
            try:
                candidate = (html_path.parent / src_clean).resolve()
                if candidate.is_file():
                    raw = candidate.read_bytes()
                    mime = mimetypes.guess_type(candidate.name)[0] or "image/jpeg"
                    entry["data_url"] = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
            except Exception:
                pass

        media.append(entry)
        marker = f"{token} {alt}" if alt else token
        img.replace_with(f" {marker} ")

    paragraphs, inline_styles = _collect_paragraphs_and_styles(soup, class_style_map)
    if not paragraphs:
        fallback = _normalize_whitespace(soup.get_text(separator=" ", strip=True))
        text = fallback
        inline_styles = []
    else:
        text = "\n\n".join(paragraphs)

    return text, media, footnotes, inline_styles


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


def _parse_spine_html_files(root: Path) -> list[Path]:
    opf_files = sorted(root.rglob("*.opf"))
    if not opf_files:
        return []
    opf_path = opf_files[0]
    try:
        xml = ET.fromstring(opf_path.read_bytes())
    except Exception:
        return []

    ns = xml.tag.split("}")[0] + "}" if "}" in xml.tag else ""
    manifest_node = xml.find(f".//{ns}manifest")
    spine_node = xml.find(f".//{ns}spine")
    if manifest_node is None or spine_node is None:
        return []

    manifest: dict[str, str] = {}
    for item in manifest_node.findall(f"{ns}item"):
        item_id = item.attrib.get("id")
        href = item.attrib.get("href")
        if item_id and href:
            manifest[item_id] = urllib.parse.unquote(href)

    ordered: list[Path] = []
    base = opf_path.parent
    for itemref in spine_node.findall(f"{ns}itemref"):
        idref = itemref.attrib.get("idref")
        if not idref or idref not in manifest:
            continue
        if itemref.attrib.get("linear", "yes").lower() == "no":
            continue
        p = (base / manifest[idref]).resolve()
        if p.suffix.lower() not in {".html", ".htm", ".xhtml"}:
            continue
        if p.exists():
            ordered.append(p)
    return ordered


def _dedupe_chapters(chapters: list[ChapterItem]) -> list[ChapterItem]:
    deduped: list[ChapterItem] = []
    seen_keys: set[tuple[str, str]] = set()
    for ch in chapters:
        compact = re.sub(r"\s+", "", ch.text or "")
        key = (ch.title.strip(), compact[:8000])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(ch)

    # Handle common mobi issue: one huge "full book" chunk + normal chapterized content.
    if len(deduped) > 1:
        avg_len = sum(len(c.text) for c in deduped) / len(deduped)
        refined: list[ChapterItem] = []
        for i, ch in enumerate(deduped):
            if len(ch.text) > avg_len * 5 and i == 0:
                continue
            refined.append(ch)
        if refined:
            deduped = refined
    return deduped


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

        spine_html_files = _parse_spine_html_files(root)
        html_files = spine_html_files if spine_html_files else sorted(
            [
                p
                for p in root.rglob("*")
                if p.suffix.lower() in {".html", ".htm", ".xhtml"}
            ]
        )

        # Some converted mobi books expose spine=['book.html'] while real chapter files are partXXXX.xhtml.
        if len(html_files) == 1 and html_files[0].name.lower() == "book.html":
            part_files = sorted(
                [
                    p
                    for p in root.rglob("*")
                    if p.suffix.lower() in {".html", ".htm", ".xhtml"}
                    and re.fullmatch(r"part\d+", p.stem.lower())
                ]
            )
            if len(part_files) >= 3:
                html_files = part_files

        if toc_map:
            toc_names = set(toc_map.keys())
            matched = [p for p in html_files if p.name.lower() in toc_names]
            if len(matched) >= max(3, len(html_files) // 3):
                html_files = matched

        if html_files:
            for p in html_files:
                raw = p.read_bytes()
                text, media, footnotes, inline_styles = _extract_html_payload(raw, p)
                if not text.strip():
                    continue
                title = toc_map.get(p.name.lower()) or _extract_title_from_html(raw)
                if not title:
                    if re.fullmatch(r"part\d+", p.stem.lower()):
                        title = f"章节 {len(chapters) + 1}"
                    else:
                        title = p.stem
                chapters.append(
                    ChapterItem(
                        title,
                        text,
                        footnotes=footnotes,
                        media=media,
                        inline_styles=inline_styles,
                    )
                )

        chapters = _dedupe_chapters(chapters)

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

    if len(chapters) == 1 and not chapters[0].media and not chapters[0].footnotes and not chapters[0].inline_styles:
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
