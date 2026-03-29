"""Tests for library service query behavior."""

import json
from datetime import datetime, timedelta
from pathlib import Path

from stonereader.models.book import Book
from stonereader.services.library_service import LibraryService


def test_service_starts_empty_without_storage(tmp_path: Path) -> None:
    service = LibraryService(storage_path=tmp_path / "books.json")
    result = service.query(scope="shelf", sort_by="title")

    assert result == []


def test_query_favorites_only(tmp_path: Path) -> None:
    service = LibraryService(storage_path=tmp_path / "books.json")
    service._books = [  # noqa: SLF001 - test prepares explicit dataset
        Book(title="A", author="x", is_favorite=True, file_path=str(tmp_path / "a.txt")),
        Book(title="B", author="x", is_favorite=False, file_path=str(tmp_path / "b.txt")),
    ]

    Path(service._books[0].file_path).write_text("a", encoding="utf-8")  # type: ignore[arg-type]
    Path(service._books[1].file_path).write_text("b", encoding="utf-8")  # type: ignore[arg-type]

    result = service.query(scope="favorites", sort_by="title")
    assert result
    assert all(book.is_favorite for book in result)


def test_query_reading_sort_uses_last_read_at(tmp_path: Path) -> None:
    service = LibraryService(storage_path=tmp_path / "books.json")
    now = datetime.now()

    service._books = [  # noqa: SLF001 - acceptable in focused unit test
        Book(title="A", author="x", last_read_at=now, file_path=str(tmp_path / "a.txt")),
        Book(title="B", author="x", last_read_at=now - timedelta(hours=1), file_path=str(tmp_path / "b.txt")),
        Book(title="C", author="x", last_read_at=None, file_path=str(tmp_path / "c.txt")),
    ]

    Path(service._books[0].file_path).write_text("a", encoding="utf-8")  # type: ignore[arg-type]
    Path(service._books[1].file_path).write_text("b", encoding="utf-8")  # type: ignore[arg-type]
    Path(service._books[2].file_path).write_text("c", encoding="utf-8")  # type: ignore[arg-type]

    result = service.query(scope="shelf", sort_by="reading")

    assert [book.title for book in result[:2]] == ["A", "B"]
    assert result[-1].title == "C"


def test_import_books_deduplicates_by_path_and_persists(tmp_path: Path) -> None:
    storage_path = tmp_path / "books.json"
    service = LibraryService(storage_path=storage_path)

    first = tmp_path / "Author A - First Book.txt"
    second = tmp_path / "Second Book.epub"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")

    added_1 = service.import_books([str(first), str(second)])
    added_2 = service.import_books([str(first)])

    assert added_1 == 2
    assert added_2 == 0

    imported = [book for book in service.query("shelf", "title") if book.file_path]
    assert any(book.title == "First Book" and book.author == "Author A" for book in imported)
    assert any("epub" in book.tags for book in imported)

    payload = json.loads(storage_path.read_text(encoding="utf-8"))
    assert len(payload["books"]) == 2

    reloaded = LibraryService(storage_path=storage_path)
    assert len(reloaded.query("shelf", "title")) == 2


def test_update_progress_persists_and_marks_read(tmp_path: Path) -> None:
    storage_path = tmp_path / "books.json"
    service = LibraryService(storage_path=storage_path)
    book_path = tmp_path / "sample.txt"
    book_path.write_text("content", encoding="utf-8")

    assert service.import_books([str(book_path)]) == 1
    service.update_progress(str(book_path), 1.0)

    reloaded = LibraryService(storage_path=storage_path)
    loaded = reloaded.get_by_path(str(book_path))
    assert loaded is not None
    assert loaded.is_read is True
    assert loaded.read_progress == 1.0
