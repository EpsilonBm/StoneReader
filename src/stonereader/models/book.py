"""Book domain model."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class Book:
    """Represents a book shown on the shelf."""

    title: str
    author: str = "Unknown"
    file_path: str | None = None
    tags: list[str] = field(default_factory=list)
    is_favorite: bool = False
    is_read: bool = False
    read_progress: float = 0.0
    added_at: datetime = field(default_factory=datetime.now)
    last_read_at: datetime | None = None
