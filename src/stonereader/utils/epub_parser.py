"""Parse EPUB files into chapters."""

import zipfile
import urllib.parse
import posixpath
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


def _normalize_whitespace(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_node_text(node) -> str:
    if node is None:
        return ""
    text = node.get_text(separator=" ", strip=True)
    return _normalize_whitespace(text)


def _collect_epub_footnotes(soup: BeautifulSoup) -> dict[str, str]:
    footnotes: dict[str, str] = {}

    id_nodes: dict[str, object] = {}
    for n in soup.find_all(attrs={"id": True}):
        nid = str(n.get("id", "")).strip()
        if nid:
            id_nodes[nid] = n

    for a in soup.find_all("a", href=True):
        href = str(a.get("href", "")).strip()
        if not href.startswith("#"):
            continue
        label = _extract_node_text(a)
        if not label:
            continue
        m = re.fullmatch(r"\[?(\d{1,4})\]?", label)
        if not m:
            continue
        num = m.group(1)
        token = f"[{num}]"
        target_id = href[1:]
        target_node = id_nodes.get(target_id)
        note_node = target_node
        if getattr(target_node, "name", "") == "a" and getattr(target_node, "parent", None) is not None:
            note_node = target_node.parent

        note_text = _extract_node_text(note_node)
        if not note_text:
            continue
        note_text = re.sub(rf"^\[?{re.escape(num)}\]?\s*", "", note_text).strip()
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

def parse_epub(file_path: str) -> list[ChapterItem]:
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
            for idref in spine:
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
                        
                for script in soup(["script", "style", "nav"]):
                    script.extract()

                footnotes = _collect_epub_footnotes(soup)
                media = _collect_epub_media_markers(soup, archive, full_path)

                paragraphs: list[str] = []
                for block in _iter_meaningful_blocks(soup):
                    p_text = _block_to_paragraph_text(block)
                    if p_text:
                        paragraphs.append(p_text)

                if not paragraphs:
                    fallback = _normalize_whitespace(soup.get_text(separator=" ", strip=True))
                    if fallback:
                        paragraphs = [fallback]

                if not paragraphs:
                    continue

                chapter_text = re.sub(r"\n{3,}", "\n\n", "\n\n".join(paragraphs)).strip()
                chapters.append(ChapterItem(title, chapter_text, footnotes=footnotes, media=media))
                
    except Exception as exc:
        import traceback
        return [ChapterItem("解析失败", f"内部错误: {str(exc)}\n{traceback.format_exc()}")]
        
    return chapters if chapters else [ChapterItem("全文", "未能解析出内容")]