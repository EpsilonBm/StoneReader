"""Simple in-memory library service for Iteration 1 UI wiring."""

from __future__ import annotations

from typing import Literal

from ..models.book import Book

SortBy = Literal["reading", "added", "title", "author"]
Scope = Literal["shelf", "favorites", "read", "tag"]


class LibraryService:
    """Holds books and provides sorted/filtered views."""

    def __init__(self) -> None:
        self._books: list[Book] = [
            Book(title="The Pragmatic Programmer", author="Andrew Hunt", tags=["coding"]),
            Book(title="Deep Work", author="Cal Newport", tags=["productivity"], is_favorite=True),
            Book(title="Animal Farm", author="George Orwell", is_read=True),
            Book(title="Clean Code", author="Robert C. Martin", tags=["coding"], is_favorite=True),
        ]

    def all_tags(self) -> list[str]:
        """Return all existing tags sorted alphabetically."""
        tags = {tag for book in self._books for tag in book.tags}
        return sorted(tags)

    def query(self, scope: Scope, sort_by: SortBy, selected_tag: str | None = None) -> list[Book]:
        """Return books by current view scope and sort strategy."""
        books = self._apply_scope(scope, selected_tag)
        return sorted(books, key=self._sort_key(sort_by))

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
            return lambda book: (book.last_read_at is None, book.last_read_at)
        if sort_by == "added":
            return lambda book: book.added_at
        if sort_by == "author":
            return lambda book: (book.author or "", book.title)
        return lambda book: (book.title, book.author)
