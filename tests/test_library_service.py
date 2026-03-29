"""Tests for library service query behavior."""

from datetime import datetime, timedelta

from stonereader.models.book import Book
from stonereader.services.library_service import LibraryService


def test_query_favorites_only() -> None:
    service = LibraryService()
    result = service.query(scope="favorites", sort_by="title")

    assert result
    assert all(book.is_favorite for book in result)


def test_query_reading_sort_uses_last_read_at() -> None:
    service = LibraryService()
    now = datetime.now()

    service._books = [  # noqa: SLF001 - acceptable in focused unit test
        Book(title="A", author="x", last_read_at=now),
        Book(title="B", author="x", last_read_at=now - timedelta(hours=1)),
        Book(title="C", author="x", last_read_at=None),
    ]

    result = service.query(scope="shelf", sort_by="reading")

    assert [book.title for book in result[:2]] == ["B", "A"]
    assert result[-1].title == "C"
