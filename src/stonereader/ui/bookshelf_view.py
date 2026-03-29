"""Center bookshelf presentation in grid/list modes."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..models.book import Book
from ..utils.screen import UiScale


class BookshelfView(QWidget):
    """Switchable widget for grid and list book views."""

    def __init__(self, ui_scale: UiScale) -> None:
        super().__init__()
        self._scale = ui_scale
        self._stack = QStackedWidget()

        self._grid_container = QWidget()
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setContentsMargins(10, 10, 10, 10)
        self._grid_layout.setHorizontalSpacing(ui_scale.spacing)
        self._grid_layout.setVerticalSpacing(ui_scale.spacing)

        self._grid_scroll = QScrollArea()
        self._grid_scroll.setWidgetResizable(True)
        self._grid_scroll.setWidget(self._grid_container)

        self._list = QListWidget()

        self._stack.addWidget(self._grid_scroll)
        self._stack.addWidget(self._list)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._stack)

    def set_grid_mode(self) -> None:
        self._stack.setCurrentIndex(0)

    def set_list_mode(self) -> None:
        self._stack.setCurrentIndex(1)

    def populate(self, books: list[Book]) -> None:
        self._populate_grid(books)
        self._populate_list(books)

    def _populate_grid(self, books: list[Book]) -> None:
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        viewport_width = max(self._grid_scroll.viewport().width(), self._scale.card_w + 40)
        columns = max(2, viewport_width // (self._scale.card_w + self._scale.spacing + 8))

        for idx, book in enumerate(books):
            row, col = divmod(idx, columns)
            self._grid_layout.addWidget(self._build_book_card(book), row, col)

        add_row, add_col = divmod(len(books), columns)
        self._grid_layout.addWidget(self._build_add_card(), add_row, add_col)
        self._grid_layout.setRowStretch(add_row + 1, 1)

    def _build_book_card(self, book: Book) -> QWidget:
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        card.setFixedSize(self._scale.card_w, self._scale.card_h)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 8, 8, 8)

        cover = QLabel("封面")
        cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover.setFixedHeight(self._scale.cover_h)
        cover.setStyleSheet("background-color: #dae3f1; border-radius: 6px;")

        title = QLabel(book.title)
        title.setWordWrap(True)
        title.setFont(QFont("Microsoft YaHei UI", 10))

        author = QLabel(book.author)
        author.setStyleSheet("color: #52616b;")

        layout.addWidget(cover)
        layout.addWidget(title)
        layout.addWidget(author)
        return card

    def _build_add_card(self) -> QWidget:
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        card.setFixedSize(self._scale.card_w, self._scale.card_h)

        layout = QVBoxLayout(card)
        add_label = QLabel("+")
        add_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        add_label.setFont(QFont("Segoe UI", 32, QFont.Weight.Bold))
        add_label.setStyleSheet("color: #4f6d7a;")
        hint = QLabel("添加书籍")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)
        layout.addWidget(add_label)
        layout.addWidget(hint)
        layout.addStretch(1)

        card.setStyleSheet("QFrame { border: 2px dashed #88a3b9; border-radius: 8px; background: #f4f8fc; }")
        return card

    def _populate_list(self, books: list[Book]) -> None:
        self._list.clear()
        for book in books:
            item = QListWidgetItem()
            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(8, 6, 8, 6)

            cover = QLabel()
            cover.setFixedSize(36, 52)
            cover.setStyleSheet("background-color: #dae3f1; border-radius: 4px;")

            title = QLabel(book.title)
            title.setFont(QFont("Microsoft YaHei UI", 10))

            author = QLabel(book.author)
            author.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            author.setStyleSheet(f"color: {QColor('#52616b').name()};")

            row.addWidget(cover)
            row.addWidget(title, 1)
            row.addWidget(author, 0)

            item.setSizeHint(row_widget.sizeHint())
            self._list.addItem(item)
            self._list.setItemWidget(item, row_widget)

        add_item = QListWidgetItem()
        add_widget = QLabel("+ 添加书籍")
        add_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        add_widget.setStyleSheet("padding: 10px; color: #4f6d7a; border: 1px dashed #88a3b9;")
        add_item.setSizeHint(add_widget.sizeHint())
        self._list.addItem(add_item)
        self._list.setItemWidget(add_item, add_widget)
