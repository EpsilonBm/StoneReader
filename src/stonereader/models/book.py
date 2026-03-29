"""Book domain model."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class Book:
    """Represents a book shown on the shelf."""

    title: str
    author: str = "Unknown"
    tags: list[str] = field(default_factory=list)
    is_favorite: bool = False
    is_read: bool = False
    added_at: datetime = field(default_factory=datetime.now)
    last_read_at: datetime | None = None
