"""Library service with local file persistence for Iteration 1."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from ..models.book import Book

SortBy = Literal["reading", "added", "title", "author"]
Scope = Literal["shelf", "favorites", "read", "tag"]


class LibraryService:
    """Holds books and provides sorted/filtered views."""

    def __init__(self, storage_path: Path | None = None) -> None:
        self._books: list[Book] = []
        self._storage_path = storage_path or self._default_storage_path()
        self._load()

    def all_tags(self) -> list[str]:
        """Return all existing tags sorted alphabetically."""
        tags = {tag for book in self._books for tag in book.tags}
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

            self._books.append(Book(title=title, author=author, file_path=resolved, tags=tags))
            existing_paths.add(resolved)
            added_count += 1

        if added_count:
            self._save()
        return added_count

    def _apply_scope(self, scope: Scope, selected_tag: str | None) -> list[Book]:
        if scope == "favorites":
            return [book for book in self._books if book.is_favorite]
        if scope == "read":
            return [book for book in self._books if book.is_read]
        if scope == "tag" and selected_tag:
            return [book for book in self._books if selected_tag in book.tags]
        return list(self._books)

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
            "tags": list(book.tags),
            "is_favorite": book.is_favorite,
            "is_read": book.is_read,
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
            tags=list(raw.get("tags", [])),
            is_favorite=bool(raw.get("is_favorite", False)),
            is_read=bool(raw.get("is_read", False)),
            added_at=datetime.fromisoformat(added_at) if added_at else datetime.now(),
            last_read_at=datetime.fromisoformat(last_read_at) if last_read_at else None,
        )
