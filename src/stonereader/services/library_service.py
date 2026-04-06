"""Library service with local file persistence for Iteration 1."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from ..models.book import Book
from ..utils.book_metadata import extract_epub_metadata, extract_mobi_metadata, save_cover_bytes

SortBy = Literal["reading", "added", "title", "author"]
Scope = Literal["shelf", "favorites", "read", "format", "tag"]


class LibraryService:
    """Holds books and provides sorted/filtered views."""

    def __init__(self, storage_path: Path | None = None) -> None:
        self._books: list[Book] = []
        self._storage_path = storage_path or self._default_storage_path()
        self._load()

    def all_tags(self) -> list[str]:
        """Return all existing tags sorted alphabetically."""
        tags = {tag for book in self._books for tag in book.custom_tags}
        return sorted(tags)

    def all_formats(self) -> list[str]:
        formats = {tag for book in self._books for tag in book.tags}
        return sorted(formats)

    def all_custom_tags(self) -> list[str]:
        tags = {tag for book in self._books for tag in book.custom_tags}
        return sorted(tags)

    def query(self, scope: Scope, sort_by: SortBy, selected_tag: str | None = None) -> list[Book]:
        """Return books by current view scope and sort strategy."""
        books = self._apply_scope(scope, selected_tag)
        return sorted(books, key=self._sort_key(sort_by), reverse=sort_by in {"reading", "added"})

    def import_books(self, file_paths: list[str]) -> int:
        """Import local files into shelf and return number of newly added books."""
        existing_paths = {book.file_path for book in self._books if book.file_path}
        added_count = 0

        for file_path in file_paths:
            resolved = str(Path(file_path).resolve())
            if not Path(resolved).exists():
                continue
            if resolved in existing_paths:
                continue

            stem = Path(resolved).stem
            author, title = self._parse_author_title(stem)
            suffix = Path(resolved).suffix.lower().lstrip(".")
            tags = [suffix] if suffix else []

            meta = self._extract_metadata(resolved)
            title = meta.get("title", title)
            author = meta.get("author", author)
            cover_path = meta.get("cover_path")

            self._books.append(
                Book(
                    title=title,
                    author=author,
                    file_path=resolved,
                    cover_path=cover_path,
                    tags=tags,
                )
            )
            existing_paths.add(resolved)
            added_count += 1

        if added_count:
            self._save()
        return added_count

    def get_by_path(self, file_path: str) -> Book | None:
        """Find a book by file path."""
        resolved = str(Path(file_path).resolve())
        for book in self._books:
            if book.file_path and str(Path(book.file_path).resolve()) == resolved:
                return book
        return None

    def update_progress(self, file_path: str, progress: float) -> None:
        """Update reading progress for a book and persist it."""
        book = self.get_by_path(file_path)
        if book is None:
            return

        bounded = min(max(progress, 0.0), 1.0)
        book.read_progress = bounded
        book.last_read_at = datetime.now()
        self._save()

    def add_custom_tag(self, file_path: str, tag: str) -> None:
        book = self.get_by_path(file_path)
        if book is None:
            return
        clean = tag.strip()
        if not clean:
            return
        if clean not in book.custom_tags:
            book.custom_tags.append(clean)
            self._save()

    def set_read_status(self, file_path: str, is_read: bool) -> None:
        book = self.get_by_path(file_path)
        if book is None:
            return
        book.is_read = is_read
        self._save()

    def set_favorite_status(self, file_path: str, is_favorite: bool) -> None:
        book = self.get_by_path(file_path)
        if book is None:
            return
        book.is_favorite = is_favorite
        self._save()

    def remove_book(self, file_path: str) -> None:
        resolved = str(Path(file_path).resolve())
        before = len(self._books)
        self._books = [
            book
            for book in self._books
            if not (book.file_path and str(Path(book.file_path).resolve()) == resolved)
        ]
        if len(self._books) != before:
            self._save()

    def update_annotations(
        self,
        file_path: str,
        bookmarks: list[dict],
        highlights: list[dict],
        notes: list[dict],
    ) -> None:
        """Update annotation payload for a book and persist immediately."""
        book = self.get_by_path(file_path)
        if book is None:
            return

        book.bookmarks = list(bookmarks)
        book.highlights = list(highlights)
        book.notes = list(notes)
        self._save()

    def _apply_scope(self, scope: Scope, selected_tag: str | None) -> list[Book]:
        if scope == "favorites":
            return [book for book in self._books if book.is_favorite]
        if scope == "read":
            return [book for book in self._books if book.is_read]
        if scope == "format" and selected_tag:
            return [book for book in self._books if selected_tag in book.tags]
        if scope == "tag" and selected_tag:
            return [book for book in self._books if selected_tag in book.custom_tags]
        return list(self._books)

    def _extract_metadata(self, file_path: str) -> dict:
        suffix = Path(file_path).suffix.lower()
        meta: dict = {}
        if suffix == ".epub":
            meta = extract_epub_metadata(file_path)
        elif suffix in {".mobi", ".azw3"}:
            meta = extract_mobi_metadata(file_path)

        cover_bytes = meta.get("cover_bytes")
        cover_ext = meta.get("cover_ext", ".jpg")
        if isinstance(cover_bytes, (bytes, bytearray)):
            cover_path = save_cover_bytes(self._storage_path.parent, file_path, bytes(cover_bytes), str(cover_ext))
            if cover_path:
                meta["cover_path"] = cover_path
        return meta

    @staticmethod
    def _sort_key(sort_by: SortBy):
        if sort_by == "reading":
            return lambda book: book.last_read_at or datetime.min
        if sort_by == "added":
            return lambda book: book.added_at
        if sort_by == "author":
            return lambda book: (book.author or "", book.title)
        return lambda book: (book.title, book.author)

    @staticmethod
    def _parse_author_title(stem: str) -> tuple[str, str]:
        """Parse common filename patterns like 'Author - Title'."""
        parts = [part.strip() for part in stem.split(" - ", maxsplit=1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            return parts[0], parts[1]
        return "Unknown", stem

    @staticmethod
    def _default_storage_path() -> Path:
        root = Path.cwd() / ".local" / "library"
        root.mkdir(parents=True, exist_ok=True)
        return root / "books.json"

    def _load(self) -> None:
        if not self._storage_path.exists():
            return

        payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
        loaded_books: list[Book] = []
        for raw in payload.get("books", []):
            file_path = raw.get("file_path")
            if not file_path:
                continue
            if not Path(file_path).exists():
                continue
            loaded_books.append(self._deserialize_book(raw))

        self._books = loaded_books
        dirty = False
        for book in self._books:
            if not book.file_path:
                continue
            needs_author = not book.author or book.author == "Unknown"
            needs_cover = not book.cover_path or not Path(book.cover_path).exists()
            if not (needs_author or needs_cover):
                continue
            meta = self._extract_metadata(book.file_path)
            if needs_author and meta.get("author"):
                book.author = meta["author"]
                dirty = True
            if needs_cover and meta.get("cover_path"):
                book.cover_path = meta["cover_path"]
                dirty = True
            if meta.get("title") and (not book.title or book.title == Path(book.file_path).stem):
                book.title = meta["title"]
                dirty = True
        if dirty:
            self._save()

    def _save(self) -> None:
        payload = {
            "books": [self._serialize_book(book) for book in self._books if book.file_path and Path(book.file_path).exists()]
        }
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._storage_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _serialize_book(book: Book) -> dict:
        return {
            "title": book.title,
            "author": book.author,
            "file_path": book.file_path,
            "cover_path": book.cover_path,
            "tags": list(book.tags),
            "custom_tags": list(book.custom_tags),
            "is_favorite": book.is_favorite,
            "is_read": book.is_read,
            "read_progress": book.read_progress,
            "bookmarks": list(book.bookmarks),
            "highlights": list(book.highlights),
            "notes": list(book.notes),
            "added_at": book.added_at.isoformat(),
            "last_read_at": book.last_read_at.isoformat() if book.last_read_at else None,
        }

    @staticmethod
    def _deserialize_book(raw: dict) -> Book:
        added_at = raw.get("added_at")
        last_read_at = raw.get("last_read_at")
        return Book(
            title=raw.get("title", "Untitled"),
            author=raw.get("author", "Unknown"),
            file_path=raw.get("file_path"),
            cover_path=raw.get("cover_path"),
            tags=list(raw.get("tags", [])),
            custom_tags=list(raw.get("custom_tags", [])),
            is_favorite=bool(raw.get("is_favorite", False)),
            is_read=bool(raw.get("is_read", False)),
            read_progress=float(raw.get("read_progress", 0.0)),
            bookmarks=list(raw.get("bookmarks", [])),
            highlights=list(raw.get("highlights", [])),
            notes=list(raw.get("notes", [])),
            added_at=datetime.fromisoformat(added_at) if added_at else datetime.now(),
            last_read_at=datetime.fromisoformat(last_read_at) if last_read_at else None,
        )
