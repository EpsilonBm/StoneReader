"""Parse EPUB files into chapters."""

import zipfile
import urllib.parse
import posixpath
from typing import Callable
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import re
import base64
import mimetypes
from pathlib import PurePosixPath

from .text_chapters import ChapterItem


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

_NOTE_HINT_RE = re.compile(r"note|foot|fn|endnote|annotation|注", flags=re.IGNORECASE)


def _normalize_whitespace(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_node_text(node) -> str:
    if node is None:
        return ""
    text = node.get_text(separator=" ", strip=True)
    return _normalize_whitespace(text)


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


def _collect_epub_footnotes(soup: BeautifulSoup) -> dict[str, str]:
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
        try:
            if note_node is not None:
                now_text = _extract_node_text(note_node)
                if token not in now_text and f"{num} " not in now_text:
                    note_node.insert(0, f"{token} ")
        except Exception:
            pass
        footnotes[token] = note_text
        footnotes[num] = note_text

    return footnotes


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
        local_styles = _collect_block_inline_styles(p_text, block, class_style_map)
        paragraphs.append(p_text)
        paragraph_styles.append(local_styles)

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


def _normalize_zip_path(path: str) -> str:
    return str(PurePosixPath(path)).lstrip("./")


def _resolve_relative_zip_path(chapter_path: str, rel_path: str) -> str:
    chapter_dir = PurePosixPath(chapter_path).parent.as_posix()
    joined = posixpath.join(chapter_dir, rel_path)
    normalized = posixpath.normpath(joined)
    return _normalize_zip_path(normalized)


def _collect_epub_media_markers(soup: BeautifulSoup, archive: zipfile.ZipFile, chapter_path: str) -> list[dict]:
    media: list[dict] = []
    for img in soup.find_all("img"):
        src = str(img.get("src", "")).strip()
        alt = str(img.get("alt", "")).strip()
        if not src and not alt:
            continue

        token = f"[图{len(media) + 1}]"
        entry = {"type": "image", "token": token, "src": src, "alt": alt}

        try:
            rel = urllib.parse.unquote(src).split("#")[0]
            if rel and not rel.lower().startswith(("http://", "https://", "data:")):
                resolved = _resolve_relative_zip_path(chapter_path, rel)
                raw = archive.read(resolved)
                mime = mimetypes.guess_type(resolved)[0] or "image/jpeg"
                entry["data_url"] = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
        except Exception:
            pass

        media.append(entry)
        marker = f"{token} {alt}" if alt else token
        img.replace_with(f" {marker} ")
    return media


def _iter_meaningful_blocks(soup: BeautifulSoup):
    body = soup.body or soup
    for node in body.descendants:
        name = getattr(node, "name", None)
        if name not in _BLOCK_TAGS:
            continue
        parent = node.parent
        nested = False
        while parent is not None and parent is not body:
            parent_name = getattr(parent, "name", None)
            if parent_name in _BLOCK_TAGS:
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

def get_namespace(tag: str) -> str:
    """Helper to extract namespace from xml tags."""
    if '}' in tag:
        return tag.split('}')[0] + '}'
    return ''

def parse_epub(file_path: str, progress: Callable[[int, str], None] | None = None) -> list[ChapterItem]:
    """Parse EPUB manually (via zip and XML) to avoid ebooklib's getchildren errors and ensure correct content order using the underlying spine."""
    chapters = []
    try:
        with zipfile.ZipFile(file_path, 'r') as archive:
            # 1. READ META-INF/container.xml
            try:
                container_data = archive.read('META-INF/container.xml')
            except KeyError:
                return [ChapterItem("解析失败", "未找到标准 EPUB 的 container.xml")]
            
            container_root = ET.fromstring(container_data)
            ns = get_namespace(container_root.tag)
            rootfile = container_root.find(f".//{ns}rootfile")
            if rootfile is None:
                return [ChapterItem("解析失败", "未从 container 中找到 rootfile (opf路径)")]
                
            opf_path = rootfile.attrib.get('full-path')
            opf_dir = opf_path.rsplit('/', 1)[0] + '/' if '/' in opf_path else ''
            
            # 2. PARSE THE .opf FILE
            opf_data = archive.read(opf_path)
            opf_root = ET.fromstring(opf_data)
            ns = get_namespace(opf_root.tag)
            
            manifest_node = opf_root.find(f".//{ns}manifest")
            spine_node = opf_root.find(f".//{ns}spine")
            
            manifest = {}
            if manifest_node is not None:
                for item in manifest_node.findall(f"{ns}item"):
                    i_id = item.attrib.get('id')
                    href = item.attrib.get('href')
                    if i_id and href:
                        manifest[i_id] = urllib.parse.unquote(href)
                        
            # Map out reading order (spine)
            spine = []
            if spine_node is not None:
                for ir in spine_node.findall(f"{ns}itemref"):
                    i_id = ir.attrib.get('idref')
                    
                    # Some EPUBs mark dedication, cover, etc. as linear='no'
                    # We skip them so “致敬”页不会被单独解析在正文中，除非 epub 配置错误
                    is_linear = ir.attrib.get('linear', 'yes').lower() != 'no'
                    if i_id and is_linear:
                        spine.append(i_id)

            # 3. PARSE TOC to map file path -> Chapter Title
            toc_mapping = {}
            toc_id = spine_node.attrib.get('toc')
            if toc_id and toc_id in manifest:
                toc_href = manifest[toc_id]
                try:
                    # usually a .ncx file
                    toc_data = archive.read(opf_dir + toc_href)
                    toc_ns = get_namespace(ET.fromstring(toc_data).tag)
                    for point in ET.fromstring(toc_data).findall(f".//{toc_ns}navPoint"):
                        t_n = point.find(f".//{toc_ns}text")
                        c_n = point.find(f"{toc_ns}content")
                        if t_n is not None and c_n is not None:
                            src = c_n.attrib.get('src')
                            if src:
                                unq = urllib.parse.unquote(src).split('#')[0]
                                if unq not in toc_mapping:
                                    toc_mapping[unq] = (t_n.text or '').strip()
                except Exception:
                    pass

            # 4. READ FILES IN SPINE ORDER
            total_spine = max(1, len(spine))
            for idx, idref in enumerate(spine):
                if progress is not None:
                    progress(int(idx * 100 / total_spine), f"正在解析章节 {idx + 1}/{total_spine}")
                if idref not in manifest: 
                    continue
                href = manifest[idref]
                
                full_path = opf_dir + href
                try:
                    html_content = archive.read(full_path)
                except KeyError: 
                    continue
                
                soup = BeautifulSoup(html_content, 'html.parser')
                
                # Fetch title from toc mapping first, fallback to DOM tags
                title = toc_mapping.get(href)
                if not title:
                    if soup.title and soup.title.string: 
                        title = soup.title.string.strip()
                    elif soup.h1: 
                        title = soup.h1.get_text(separator=' ', strip=True)
                    elif soup.h2: 
                        title = soup.h2.get_text(separator=' ', strip=True)
                    else: 
                        title = "未知章节"

                class_style_map = _collect_class_style_map(soup)
                        
                for script in soup(["script", "style", "nav"]):
                    script.extract()

                footnotes = _collect_epub_footnotes(soup)
                media = _collect_epub_media_markers(soup, archive, full_path)

                paragraphs, inline_styles = _collect_paragraphs_and_styles(soup, class_style_map)

                if not paragraphs:
                    fallback = _normalize_whitespace(soup.get_text(separator=" ", strip=True))
                    if fallback:
                        paragraphs = [fallback]
                        inline_styles = []

                if not paragraphs:
                    continue

                chapter_text = re.sub(r"\n{3,}", "\n\n", "\n\n".join(paragraphs)).strip()
                chapters.append(
                    ChapterItem(
                        title,
                        chapter_text,
                        footnotes=footnotes,
                        media=media,
                        inline_styles=inline_styles,
                    )
                )
            if progress is not None:
                progress(100, "章节解析完成")
                
    except Exception as exc:
        import traceback
        return [ChapterItem("解析失败", f"内部错误: {str(exc)}\n{traceback.format_exc()}")]
        
    return chapters if chapters else [ChapterItem("全文", "未能解析出内容")]