"""Parse EPUB files into chapters."""

from pathlib import Path

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

from .text_chapters import ChapterItem

def parse_epub(file_path: str) -> list[ChapterItem]:
    """Parse EPUB and extract chapter texts."""
    try:
        book = epub.read_epub(file_path)
    except Exception as exc:
        return [ChapterItem("解析失败", f"EPUB 解析错误: {exc}")]
        
    chapters = []
    
    # Collect items that are documents
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            html_content = item.get_body_content()
            if not html_content:
                continue
                
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Try to grab a title
            title = "未知章节"
            if soup.title and soup.title.string:
                title = soup.title.string.strip()
            elif soup.h1:
                title = soup.h1.get_text(strip=True)
            elif soup.h2:
                title = soup.h2.get_text(strip=True)
                
            text = soup.get_text(separator='\n', strip=True)
            if not text.strip():
                continue
                
            # Basic formatting
            cleaned = []
            for line in text.splitlines():
                s = line.strip()
                if s:
                    cleaned.append("　　" + s)
                else:
                    cleaned.append("")
                    
            chapter_text = "\n".join(cleaned)
            chapters.append(ChapterItem(title, chapter_text))
            
    if not chapters:
        chapters = [ChapterItem("全文", "未提取到任何有效文本或章节。")]
        
    return chapters