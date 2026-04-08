"""Parse MOBI/AZW3 files into chapter items."""

from __future__ import annotations

from pathlib import Path
from typing import Callable
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
    "div",
    "section",
    "figure",
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


def _collect_mobi_footnotes(
    soup: BeautifulSoup,
    html_name: str,
    global_note_targets: dict[str, str] | None = None,
) -> dict[str, str]:
    footnotes: dict[str, str] = {}
    target_token_map: dict[str, str] = {}
    token_use_count: dict[str, int] = {}
    seq = 1
    max_anchors = 5000
    max_notes = 1200

    id_nodes: dict[str, object] = {}
    for n in soup.find_all(attrs={"id": True}):
        nid = str(n.get("id", "")).strip()
        if nid:
            id_nodes[nid] = n

    note_like_ids = {
        nid
        for nid in id_nodes.keys()
        if _NOTE_HINT_RE.search(nid)
        or re.search(r"(?:^|[-_])(fn|note|footnote|endnote)\d*$", nid, flags=re.IGNORECASE)
    }

    def _pick_note_container(node):
        cur = node
        for _ in range(6):
            if cur is None:
                return None
            name = str(getattr(cur, "name", "") or "").lower()
            if name in {"li", "p", "div", "aside", "section", "td", "dd"}:
                return cur
            cur = getattr(cur, "parent", None)
        return node

    def _note_text_matches_token(note_text: str, num_text: str, token_text: str) -> bool:
        t = (note_text or "").strip()
        if not t:
            return False
        if token_text and t.startswith(token_text):
            return True
        if num_text:
            if re.match(rf"^\[?\s*(?:注\s*)?{re.escape(num_text)}\s*\]?", t):
                return True
            if re.match(rf"^\(?\s*{re.escape(num_text)}\s*[\)）.]", t):
                return True
        return False

    for idx, a in enumerate(soup.find_all("a", href=True)):
        if idx >= max_anchors or len(footnotes) >= max_notes * 2:
            break
        href = str(a.get("href", "")).strip()
        if "#" not in href:
            continue
        href_file_raw, target_id = href.split("#", 1)
        href_file = Path(urllib.parse.unquote(href_file_raw)).name.lower().strip()
        target_id = target_id.strip()
        if not target_id:
            continue
        cross_file = bool(href_file and href_file != html_name.lower())
        has_local_target = target_id in id_nodes
        global_key = f"{href_file}#{target_id.lower()}" if href_file else f"#{target_id.lower()}"
        if href_file:
            has_global_target = bool(global_note_targets and (global_key in global_note_targets))
        else:
            has_global_target = bool(global_note_targets and (f"#{target_id.lower()}" in global_note_targets))
        if not has_local_target and not has_global_target:
            continue
        label = _extract_node_text(a)
        m = re.search(r"(\d{1,4})", label)
        parent_name = str(getattr(a.parent, "name", "") or "").lower()
        note_hint = bool(
            target_id in note_like_ids
            or
            _NOTE_HINT_RE.search(href)
            or _NOTE_HINT_RE.search(target_id)
            or _NOTE_HINT_RE.search(label)
            or parent_name in {"sup", "sub"}
        )
        if not note_hint:
            # 对纯数字锚点更保守：只接受上/下标短标签，避免把正文目录链接误判为脚注。
            target_norm = target_id.lower()
            fast_note_target = bool(re.fullmatch(r"[mfn]\d{1,4}", target_norm))
            if not (m and len(label) <= 12 and (parent_name in {"sup", "sub"} or fast_note_target)):
                continue

        if not m and not note_hint:
            continue

        if target_id in target_token_map:
            token = target_token_map[target_id]
        elif m:
            base_num = m.group(1)
            base_token = f"[{base_num}]"
            used = token_use_count.get(base_token, 0)
            if used <= 0:
                token = base_token
                token_use_count[base_token] = 1
            else:
                token = f"[{base_num}-{used + 1}]"
                token_use_count[base_token] = used + 1
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

        # 常见回跳锚点（w1/w2...）指向正文，不应作为脚注内容。
        if re.fullmatch(r"w\d{1,4}", target_id, flags=re.IGNORECASE):
            continue

        note_text = ""
        target_node = id_nodes.get(target_id)
        if target_node is not None:
            note_node = target_node
            if getattr(target_node, "name", "") == "a" and getattr(target_node, "parent", None) is not None:
                note_node = target_node.parent
            note_node = _pick_note_container(note_node)
            note_text = _extract_node_text(note_node)

        if not note_text and global_note_targets:
            if href_file:
                note_text = global_note_targets.get(global_key, "")
            else:
                note_text = global_note_targets.get(f"#{target_id.lower()}", "")
        if not note_text:
            continue
        if not cross_file and not _note_text_matches_token(note_text, num, token) and len(note_text) > 120:
            # Calibre 类策略：正文回跳目标通常不以编号起始，且文本偏长，判为非脚注。
            continue
        if not cross_file and len(note_text) > 260 and not (
            _NOTE_HINT_RE.search(href) or _NOTE_HINT_RE.search(target_id)
        ):
            # 同文件且无明显注释特征时，长文本大概率是正文锚点，避免“脚注内容=被注释正文”。
            continue
        if len(note_text) > 800:
            # 极长文本通常不是脚注容器（会导致性能灾难和误识别）。
            continue
        note_text = re.sub(r"^\[?\s*(?:注\s*)?\d{1,4}\s*\]?\s*", "", note_text).strip()
        if not note_text:
            continue
        footnotes[token] = note_text
        # 仅在数字键不存在时写入数字别名，避免同编号多脚注覆盖导致串文。
        if num and num not in footnotes:
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


def _collect_anchor_offsets(soup: BeautifulSoup) -> dict[str, int]:
    """Map anchor ids like filepos123 -> normalized chapter text offset.

    Offsets are computed in the same paragraph-join model used by parser text output,
    so they can be used directly as chapter boundaries.
    """
    anchors: dict[str, int] = {}
    cursor = 0
    blocks = list(_iter_meaningful_blocks(soup))
    block_offsets: dict[int, int] = {}

    def _normalize_anchor_id(raw: str) -> str:
        return str(raw or "").strip().lower()

    def _is_valid_anchor_id(aid: str) -> bool:
        if not aid:
            return False
        if len(aid) > 128:
            return False
        # filepos123 / chp3-1 / note_12 / fn:3 等都允许。
        return bool(re.fullmatch(r"[a-z0-9_.:\-]+", aid))

    def _collect_ids(node) -> list[str]:
        ids: list[str] = []
        for key in ("id", "name"):
            val = _normalize_anchor_id(str(node.get(key, "") or ""))
            if _is_valid_anchor_id(val):
                ids.append(val)
        return ids

    for idx, block in enumerate(blocks):
        p_text = _block_to_paragraph_text(block)
        if not p_text:
            continue
        block_offsets[id(block)] = cursor

        block_ids = _collect_ids(block)
        for a in block.find_all(attrs={"id": True}):
            block_ids.extend(_collect_ids(a))
        for a in block.find_all(attrs={"name": True}):
            block_ids.extend(_collect_ids(a))

        seen: set[str] = set()
        for aid in block_ids:
            aid = aid.lower()
            if aid in seen:
                continue
            seen.add(aid)
            anchors.setdefault(aid, cursor)

        cursor += len(p_text)
        if idx < len(blocks) - 1:
            cursor += 2

    # Anchor tags are often empty and located before real paragraph blocks.
    # Resolve them to nearest following meaningful block offset.
    for node in soup.find_all(attrs={"id": True}) + soup.find_all(attrs={"name": True}):
        vals: list[str] = []
        for key in ("id", "name"):
            val = _normalize_anchor_id(str(node.get(key, "") or ""))
            if _is_valid_anchor_id(val):
                vals.append(val)
        if not vals:
            continue

        resolved: int | None = None
        cur = node
        # If anchor is inside a meaningful block, use that block's start.
        while cur is not None:
            off = block_offsets.get(id(cur))
            if off is not None:
                resolved = off
                break
            cur = getattr(cur, "parent", None)

        # Otherwise map to nearest following meaningful block.
        if resolved is None:
            for nxt in node.next_elements:
                off = block_offsets.get(id(nxt))
                if off is not None:
                    resolved = off
                    break

        if resolved is None:
            continue
        for a in vals:
            anchors.setdefault(a, resolved)

    return anchors


def _build_global_note_targets(root: Path, html_files: list[Path]) -> dict[str, str]:
    out: dict[str, str] = {}
    if not html_files:
        return out

    def _note_like_id(aid: str) -> bool:
        if not aid:
            return False
        if _NOTE_HINT_RE.search(aid):
            return True
        if re.fullmatch(r"[abmn]?\d{1,4}", aid, flags=re.IGNORECASE):
            return True
        if re.fullmatch(r"(?:fn|ref|note|endnote)[-_]?[a-z0-9]{1,8}", aid, flags=re.IGNORECASE):
            return True
        return False

    for p in html_files:
        try:
            soup = _parse_document(p.read_bytes())
        except Exception:
            continue
        for bad in soup(["script", "style", "nav"]):
            bad.extract()

        id_nodes: dict[str, object] = {}
        for n in soup.find_all(attrs={"id": True}):
            nid = str(n.get("id", "") or "").strip()
            if nid:
                id_nodes[nid] = n
        for n in soup.find_all(attrs={"name": True}):
            nid = str(n.get("name", "") or "").strip()
            if nid and nid not in id_nodes:
                id_nodes[nid] = n

        for nid, node in id_nodes.items():
            if not _note_like_id(nid):
                continue
            container = node
            if getattr(node, "name", "") == "a" and getattr(node, "parent", None) is not None:
                container = node.parent
            text = _extract_node_text(container)
            if len(text) < 2 or len(text) > 800:
                continue
            norm_id = nid.lower()
            out.setdefault(f"{p.name.lower()}#{norm_id}", text)
            out.setdefault(f"#{norm_id}", text)
    return out


def _extract_html_payload(
    content: bytes,
    html_path: Path,
    global_note_targets: dict[str, str] | None = None,
) -> tuple[str, list[dict], dict[str, str], list[dict], dict[str, int]]:
    soup = _parse_document(content)
    class_style_map = _collect_class_style_map(soup)
    for bad in soup(["script", "style", "nav"]):
        bad.extract()

    footnotes = _collect_mobi_footnotes(soup, html_path.name, global_note_targets=global_note_targets)

    def _is_inline_image(img_node) -> bool:
        parent = getattr(img_node, "parent", None)
        pname = str(getattr(parent, "name", "") or "").lower()
        if pname not in {"p", "span", "a", "em", "strong", "b", "i", "u", "sup", "sub", "li"}:
            return False
        if parent is None:
            return False
        # 同父节点含有效文本，判定为行内图；纯图段落仍按块级处理。
        sibling_text = " ".join(s for s in parent.stripped_strings)
        return bool(_normalize_whitespace(sibling_text))

    media: list[dict] = []
    for img in soup.find_all("img"):
        src = str(img.get("src", "")).strip()
        alt = str(img.get("alt", "")).strip()
        if not src and not alt:
            continue

        token = f"[图{len(media) + 1}]"
        entry = {
            "type": "image",
            "token": token,
            "src": src,
            "alt": alt,
            "inline": _is_inline_image(img),
        }

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
    anchor_offsets = _collect_anchor_offsets(soup)
    if not paragraphs:
        fallback = _normalize_whitespace(soup.get_text(separator=" ", strip=True))
        text = fallback
        inline_styles = []
    else:
        text = "\n\n".join(paragraphs)

    if text and media:
        cursor = 0
        for m in media:
            tk = str(m.get("token", "")).strip()
            if not tk:
                continue
            pos = text.find(tk, cursor)
            if pos < 0:
                pos = text.find(tk)
            if pos >= 0:
                m["text_pos"] = pos
                cursor = pos + len(tk)

    return text, media, footnotes, inline_styles, anchor_offsets


def _extract_cover_media_from_html(html_path: Path) -> list[dict]:
    try:
        soup = _parse_document(html_path.read_bytes())
    except Exception:
        return []
    img = soup.find("img")
    if img is None:
        return []
    src = str(img.get("src", "")).strip()
    alt = str(img.get("alt", "")).strip() or "封面"
    if not src:
        return []

    entry = {"type": "image", "token": "[图1]", "src": src, "alt": alt}
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
    if not entry.get("data_url"):
        return []
    return [entry]


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


def _parse_ncx_navpoints(root: Path) -> list[tuple[str, str, str, int]]:
    """Return ordered (title, file_name, fragment, depth) navpoints from NCX."""
    out: list[tuple[str, str, str, int]] = []
    ncx_files = sorted(root.rglob("*.ncx"))
    if not ncx_files:
        return out
    try:
        data = ncx_files[0].read_bytes()
        xml = ET.fromstring(data)
        ns = xml.tag.split("}")[0] + "}" if "}" in xml.tag else ""
        nav_map = xml.find(f".//{ns}navMap")
        if nav_map is None:
            return out

        def _walk(nodes: list[ET.Element], depth: int) -> None:
            for navpoint in nodes:
                text_node = navpoint.find(f".//{ns}text")
                content_node = navpoint.find(f"{ns}content")
                if text_node is not None and content_node is not None:
                    title = (text_node.text or "").strip()
                    src = urllib.parse.unquote(content_node.attrib.get("src", "")).strip()
                    if title and src:
                        href, _, frag = src.partition("#")
                        file_name = Path(href).name.lower() if href else ""
                        out.append((title, file_name, frag.lower(), depth))
                children = navpoint.findall(f"{ns}navPoint")
                if children:
                    _walk(children, depth + 1)

        _walk(nav_map.findall(f"{ns}navPoint"), 1)
    except Exception:
        return out
    return out


def _split_by_ncx_anchors(
    title: str,
    text: str,
    media: list[dict],
    footnotes: dict[str, str],
    anchor_offsets: dict[str, int],
    navpoints: list[tuple[str, str, str, int]],
    html_name: str,
) -> list[ChapterItem]:
    if not text or not anchor_offsets or not navpoints:
        return []

    file_key = html_name.lower()
    points: list[tuple[int, str, int]] = []
    for nav_title, nav_file, frag, depth in navpoints:
        if nav_file and nav_file != file_key:
            continue
        if not frag:
            continue
        pos = anchor_offsets.get(frag)
        if pos is None:
            continue
        points.append((pos, nav_title.strip(), int(depth)))

    if len(points) < 2:
        return []

    # stable dedupe by offset
    def _title_rank(title_text: str, depth: int) -> tuple[int, int, int]:
        t = re.sub(r"\s+", "", title_text)
        if re.fullmatch(r"第[一二三四五六七八九十百千万0-9]+章", t):
            return (3, depth, len(t))
        if re.fullmatch(r"第[一二三四五六七八九十百千万0-9]+部", t):
            return (2, depth, len(t))
        if re.fullmatch(r"第[一二三四五六七八九十百千万0-9]+卷", t):
            return (2, depth, len(t))
        return (1, depth, len(t))

    points.sort(key=lambda x: x[0])
    uniq: list[tuple[int, str]] = []
    for pos, t, depth in points:
        t_norm = re.sub(r"\s+", "", t)
        if not uniq:
            uniq.append((pos, t_norm))
            continue
        last_pos, last_title = uniq[-1]
        if pos == last_pos:
            if _title_rank(t_norm, depth) > _title_rank(last_title, 1):
                uniq[-1] = (pos, t_norm)
            continue
        if pos < last_pos:
            continue
        uniq.append((pos, t_norm))

    if len(uniq) < 2:
        return []

    token_re = re.compile(r"\[图\d{1,4}\]")
    media_by_token = {str(m.get("token", "")): m for m in media}

    def _clone_media_for_chunk(src_media: dict, chunk_start: int) -> dict:
        cloned = dict(src_media)
        m_pos = src_media.get("text_pos")
        if isinstance(m_pos, int):
            cloned["text_pos"] = max(0, m_pos - chunk_start)
        else:
            cloned.pop("text_pos", None)
        return cloned

    out: list[ChapterItem] = []
    assigned: set[str] = set()
    current_part = ""
    part_re = re.compile(r"^第[一二三四五六七八九十百千万0-9]+[部卷]$")
    chapter_re = re.compile(r"^第[一二三四五六七八九十百千万0-9]+章")

    for i, (start, nav_title) in enumerate(uniq):
        if part_re.fullmatch(nav_title):
            current_part = nav_title
        end = uniq[i + 1][0] if i + 1 < len(uniq) else len(text)
        if end - start < 80:
            continue
        chunk = text[start:end].strip()
        if len(chunk) < 80:
            continue

        display_title = nav_title or f"章节 {i+1}"
        if chapter_re.match(display_title) and current_part and current_part not in display_title:
            display_title = f"{current_part} {display_title}"

        local_media: list[dict] = []
        seen_ids: set[int] = set()

        for m in media:
            m_pos = m.get("text_pos")
            if not isinstance(m_pos, int):
                continue
            if start <= m_pos < end:
                mid = id(m)
                if mid in seen_ids:
                    continue
                seen_ids.add(mid)
                local_media.append(_clone_media_for_chunk(m, start))
                tk = str(m.get("token", "")).strip()
                if tk:
                    assigned.add(tk)

        if not local_media:
            seen: set[str] = set()
            for tk in token_re.findall(chunk):
                if tk in seen:
                    continue
                seen.add(tk)
                m = media_by_token.get(tk)
                if m is not None:
                    local_media.append(_clone_media_for_chunk(m, start))
                    assigned.add(tk)

        out.append(
            ChapterItem(
                title=display_title,
                text=chunk,
                footnotes=dict(footnotes),
                media=local_media,
                inline_styles=[],
            )
        )

    if len(out) < 2:
        return []

    # If some images are not assigned due to boundary mismatch, map by nearest chapter start.
    remaining = [m for tk, m in media_by_token.items() if tk and tk not in assigned]
    if remaining:
        starts = [s for s, _ in uniq]
        for m in remaining:
            m_pos = m.get("text_pos")
            if not isinstance(m_pos, int):
                out[0].media.append(_clone_media_for_chunk(m, 0))
                continue
            target_idx = 0
            for i2, st in enumerate(starts):
                if st <= m_pos:
                    target_idx = i2
                else:
                    break
            target_idx = max(0, min(target_idx, len(out) - 1))
            out[target_idx].media.append(_clone_media_for_chunk(m, starts[target_idx]))
    return out


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


def _split_huge_single_chapter(chapter: ChapterItem) -> list[ChapterItem]:
    text = chapter.text or ""
    if len(text) < 300_000:
        return [chapter]

    paragraphs = text.split("\n\n")
    if len(paragraphs) < 200:
        return [chapter]

    def _is_heading_candidate(s: str) -> bool:
        if not s:
            return False
        if re.fullmatch(r"\[图\d{1,4}\]", s):
            return False
        if len(s) > 24:
            return False
        if re.search(r"[，。！？；：“”,.!?;:…]", s):
            return False
        # 通用噪声词（版权/封面/目录类），避免将前置信息误识别为章节标题。
        if re.search(r"作者|译者|出版|版权|目录|封面|扉页|插图|illustration", s, flags=re.IGNORECASE):
            return False
        if re.fullmatch(r"【第[一二三四五六七八九十0-9]+卷】", s):
            return True
        if re.fullmatch(r"(序章|序幕|终章|跋)", s):
            return True
        if s.startswith("附录"):
            return True
        if re.fullmatch(r"第[一二三四五六七八九十百千万0-9]+章", s):
            return True
        if re.fullmatch(r"[\u4e00-\u9fffA-Za-z·]{2,10}", s):
            return True
        return False

    para_offsets: list[int] = []
    cursor = 0
    for i, p in enumerate(paragraphs):
        para_offsets.append(cursor)
        cursor += len(p)
        if i < len(paragraphs) - 1:
            cursor += 2

    candidates: list[tuple[int, str]] = []
    for i, p in enumerate(paragraphs):
        t = p.strip()
        if _is_heading_candidate(t):
            candidates.append((para_offsets[i], t))

    if len(candidates) < 8:
        return [chapter]

    title_counts: dict[str, int] = {}
    for _, t in candidates:
        title_counts[t] = title_counts.get(t, 0) + 1

    # 跳过前言/目录区域：寻找“重复出现或强章节模式”的第一个候选。
    strong_title_re = re.compile(r"^【第[一二三四五六七八九十0-9]+卷】$|^(序章|序幕|终章|跋)$|^附录|^第[一二三四五六七八九十百千万0-9]+章$")
    warmup_floor = max(1000, int(len(text) * 0.0015))
    start_idx = 0
    for i, (pos, title) in enumerate(candidates):
        cnt = title_counts.get(title, 0)
        # 过高频（例如页眉）跳过；重复但不过高频的短标题通常是有效章标题。
        if cnt > max(80, len(candidates) // 6):
            continue
        if pos > warmup_floor and (strong_title_re.search(title) or cnt >= 2):
            start_idx = i
            break

    filtered: list[tuple[int, str]] = []
    min_gap = max(700, min(2200, len(text) // 1800))
    last_pos = -10**9
    for pos, title in candidates[start_idx:]:
        cnt = title_counts.get(title, 0)
        if cnt > max(80, len(candidates) // 6):
            continue
        if pos - last_pos < min_gap:
            continue
        filtered.append((pos, title))
        last_pos = pos

    if len(filtered) < 8:
        return [chapter]

    # 保护：避免过度切分
    if len(filtered) > 1200:
        return [chapter]

    token_re = re.compile(r"\[图\d{1,4}\]")
    media_by_token = {str(m.get("token", "")): m for m in chapter.media}

    out: list[ChapterItem] = []
    assigned_tokens: set[str] = set()

    first_start = filtered[0][0]
    if first_start > 300:
        prefix = text[:first_start].strip()
        if len(prefix) >= 120:
            local_media: list[dict] = []
            seen: set[str] = set()
            for tk in token_re.findall(prefix):
                if tk in seen:
                    continue
                seen.add(tk)
                m = media_by_token.get(tk)
                if m is not None:
                    local_media.append(m)
                    assigned_tokens.add(tk)
            out.append(
                ChapterItem(
                    title="前言",
                    text=prefix,
                    footnotes=dict(chapter.footnotes),
                    media=local_media,
                    inline_styles=[],
                )
            )

    for i, (start, title) in enumerate(filtered):
        end = filtered[i + 1][0] if i + 1 < len(filtered) else len(text)
        if end <= start:
            continue
        chunk = text[start:end].strip()
        if len(chunk) < 120:
            continue

        chapter_title = re.sub(r"\s+", "", title).strip() or "章节"

        local_media: list[dict] = []
        seen: set[str] = set()
        for tk in token_re.findall(chunk):
            if tk in seen:
                continue
            seen.add(tk)
            m = media_by_token.get(tk)
            if m is not None:
                local_media.append(m)
                assigned_tokens.add(tk)

        out.append(
            ChapterItem(
                title=chapter_title,
                text=chunk,
                footnotes=dict(chapter.footnotes),
                media=local_media,
                inline_styles=[],
            )
        )

    if len(out) < 2:
        return [chapter]

    remaining = [m for tk, m in media_by_token.items() if tk and tk not in assigned_tokens]
    if remaining:
        out[0].media.extend(remaining)
    return out


def _looks_structured_title(title: str) -> bool:
    t = re.sub(r"\s+", "", title or "")
    if not t:
        return False
    if re.fullmatch(r"第[一二三四五六七八九十百千万0-9]+章.*", t):
        return True
    if re.fullmatch(r"第[一二三四五六七八九十百千万0-9]+部.*", t):
        return True
    if re.fullmatch(r"第[一二三四五六七八九十百千万0-9]+卷.*", t):
        return True
    return False


def _merge_unknown_bridge_chapters(chapters: list[ChapterItem]) -> list[ChapterItem]:
    if not chapters:
        return chapters

    unknown_re = re.compile(r"^(未知|未知章节|chapter)$", flags=re.IGNORECASE)
    merged: list[ChapterItem] = []
    for ch in chapters:
        if (
            merged
            and unknown_re.fullmatch((ch.title or "").strip())
            and _looks_structured_title(merged[-1].title)
            and len(merged[-1].text.strip()) <= 280
            and len(ch.text.strip()) >= 600
        ):
            prev = merged[-1]
            prev_old = prev.text or ""
            prev.text = (prev_old.rstrip() + "\n\n" + ch.text.lstrip()).strip()
            if ch.media:
                base_shift = len(prev_old.rstrip())
                if base_shift > 0:
                    base_shift += 2
                for m in ch.media:
                    cloned = dict(m)
                    m_pos = m.get("text_pos")
                    if isinstance(m_pos, int):
                        cloned["text_pos"] = m_pos + base_shift
                    prev.media.append(cloned)
            if ch.footnotes:
                prev.footnotes.update(ch.footnotes)
            if ch.inline_styles:
                prev.inline_styles.extend(ch.inline_styles)
            continue
        merged.append(ch)
    return merged


def _ensure_media_tokens_in_text(chapters: list[ChapterItem]) -> None:
    for ch in chapters:
        if not ch.media:
            continue
        text = ch.text or ""
        appended: list[str] = []
        for m in ch.media:
            token = str(m.get("token", "")).strip()
            if not token:
                continue
            if token not in text and token not in appended:
                appended.append(token)
        if appended:
            # 缺失token属兜底场景，追加到末尾避免干扰正文原始顺序定位。
            ch.text = (text.rstrip() + "\n\n" + "\n".join(appended)).strip()


def _normalize_media_tokens(chapters: list[ChapterItem]) -> None:
    token_re = re.compile(r"\[图\d{1,4}\]")
    for ch in chapters:
        if not ch.media:
            continue

        # 统一 media token 编号，避免合并章节后出现重复 [图1] 导致定位偏差。
        for idx, m in enumerate(ch.media, start=1):
            m["token"] = f"[图{idx}]"

        expected = len(ch.media)
        seq = 0

        def _repl(_match: re.Match[str]) -> str:
            nonlocal seq
            seq += 1
            if seq <= expected:
                return f"[图{seq}]"
            return _match.group(0)

        ch.text = token_re.sub(_repl, ch.text or "")

        # 归一化后回填 text_pos，供渲染阶段精确定位。
        cursor = 0
        for m in ch.media:
            tk = str(m.get("token", "")).strip()
            if not tk:
                m.pop("text_pos", None)
                continue
            pos = ch.text.find(tk, cursor)
            if pos < 0:
                pos = ch.text.find(tk)
            if pos >= 0:
                m["text_pos"] = pos
                cursor = pos + len(tk)
            else:
                m.pop("text_pos", None)


def _prune_duplicate_cover_chapters(chapters: list[ChapterItem]) -> list[ChapterItem]:
    if not chapters:
        return chapters
    cover_indexes = [i for i, c in enumerate(chapters) if (c.title or "").strip().lower() == "cover"]
    if len(cover_indexes) <= 1:
        return chapters
    keep_idx = cover_indexes[0]
    for i in cover_indexes:
        if len(chapters[i].media) > len(chapters[keep_idx].media):
            keep_idx = i
    out: list[ChapterItem] = []
    for i, ch in enumerate(chapters):
        if i in cover_indexes and i != keep_idx:
            continue
        out.append(ch)
    return out


def _drop_empty_cover_chapters(chapters: list[ChapterItem]) -> list[ChapterItem]:
    out: list[ChapterItem] = []
    for ch in chapters:
        t = (ch.title or "").strip().lower()
        body = (ch.text or "").strip().lower()
        if t == "cover" and not ch.media and body in {"", "cover", "封面"}:
            continue
        out.append(ch)
    return out


def _rebuild_media_text_positions(chapters: list[ChapterItem]) -> None:
    for ch in chapters:
        if not ch.media:
            continue
        cursor = 0
        text = ch.text or ""
        for m in ch.media:
            tk = str(m.get("token", "")).strip()
            if not tk:
                m.pop("text_pos", None)
                continue
            pos = text.find(tk, cursor)
            if pos < 0:
                pos = text.find(tk)
            if pos >= 0:
                m["text_pos"] = pos
                cursor = pos + len(tk)
            else:
                m.pop("text_pos", None)


def parse_mobi(file_path: str, progress: Callable[[int, str], None] | None = None) -> list[ChapterItem]:
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
        navpoints = _parse_ncx_navpoints(root)
        # 不再强制注入 synthetic cover，避免封面错图干扰正文阅读。

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

        toc_names: set[str] = set(toc_map.keys()) if toc_map else set()
        toc_trusted = False

        if toc_map:
            matched = [p for p in html_files if p.name.lower() in toc_names]
            if len(matched) >= max(3, len(html_files) // 3):
                toc_trusted = True
                skipped = [p for p in html_files if p not in matched]
                lightweight_front: list[Path] = []
                for sp in skipped:
                    try:
                        soup = _parse_document(sp.read_bytes())
                        img_count = len(soup.find_all("img"))
                        text_len = len(_normalize_whitespace(soup.get_text(" ", strip=True)))
                    except Exception:
                        continue
                    if img_count > 0 and text_len < 80:
                        lightweight_front.append(sp)
                html_files = lightweight_front + matched

        global_note_targets = _build_global_note_targets(root, html_files)

        if html_files:
            total_files = max(1, len(html_files))
            for idx, p in enumerate(html_files):
                if progress is not None:
                    progress(int(idx * 100 / total_files), f"正在解析章节文件 {idx + 1}/{total_files}")
                raw = p.read_bytes()
                text, media, footnotes, inline_styles, anchor_offsets = _extract_html_payload(
                    raw,
                    p,
                    global_note_targets=global_note_targets,
                )
                if not text.strip():
                    continue

                if toc_trusted and p.name.lower() not in toc_names and re.fullmatch(r"part\d+", p.stem.lower()):
                    # TOC可信时，跳过未收录part噪声页（常见于转换残留封页/空白页）。
                    continue

                # Prefer TOC-anchor driven split for single-html books (generic and stable).
                toc_split = _split_by_ncx_anchors(
                    title=p.stem,
                    text=text,
                    media=media,
                    footnotes=footnotes,
                    anchor_offsets=anchor_offsets,
                    navpoints=navpoints,
                    html_name=p.name,
                )
                if len(toc_split) > 1:
                    chapters.extend(toc_split)
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
            if progress is not None:
                progress(100, "章节解析完成")

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

    if len(chapters) == 1:
        chapters = _split_huge_single_chapter(chapters[0])

    # 通用保护：任何残留超长章节都按体积软切分，降低渲染重叠/卡顿风险。
    protected: list[ChapterItem] = []
    for ch in chapters:
        if len(ch.text) <= 80_000:
            protected.append(ch)
            continue
        text = ch.text
        block = 35_000
        cursor = 0
        part_idx = 1
        while cursor < len(text):
            end = min(len(text), cursor + block)
            if end < len(text):
                pivot = text.rfind("\n\n", cursor + int(block * 0.6), end)
                if pivot > cursor + 500:
                    end = pivot
            chunk = text[cursor:end].strip()
            if chunk:
                title = ch.title if part_idx == 1 else f"{ch.title}（续{part_idx}）"
                protected.append(
                    ChapterItem(
                        title=title,
                        text=chunk,
                        footnotes=dict(ch.footnotes),
                        media=[] if part_idx > 1 else list(ch.media),
                        inline_styles=[],
                    )
                )
                part_idx += 1
            cursor = max(end + 2, cursor + 1)
    chapters = protected
    chapters = _prune_duplicate_cover_chapters(chapters)
    chapters = _drop_empty_cover_chapters(chapters)

    chapters = _merge_unknown_bridge_chapters(chapters)
    _normalize_media_tokens(chapters)
    _ensure_media_tokens_in_text(chapters)
    _rebuild_media_text_positions(chapters)

    if not chapters:
        return [ChapterItem("全文", "未提取到可阅读文本，可能为图片型电子书。")]
    return chapters
