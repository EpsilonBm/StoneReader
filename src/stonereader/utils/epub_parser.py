"""Parse EPUB files into chapters."""

import zipfile
import urllib.parse
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET

from .text_chapters import ChapterItem

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
                    
                text_content = soup.get_text(separator='\n', strip=True)
                if not text_content.strip(): 
                    continue
                
                cleaned = []
                for line in text_content.split('\n'):
                    line = line.strip()
                    if line: 
                        cleaned.append("　　" + line)
                    else: 
                        cleaned.append("")
                
                import re
                chapter_text = re.sub(r'\n{3,}', '\n\n', "\n".join(cleaned))
                chapters.append(ChapterItem(title, chapter_text))
                
    except Exception as exc:
        import traceback
        return [ChapterItem("解析失败", f"内部错误: {str(exc)}\n{traceback.format_exc()}")]
        
    return chapters if chapters else [ChapterItem("全文", "未能解析出内容")]