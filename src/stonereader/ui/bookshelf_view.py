"""Center bookshelf presentation in grid/list modes."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QResizeEvent, QPixmap
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

    addRequested = pyqtSignal()
    openRequested = pyqtSignal(str)
    manageRequested = pyqtSignal(str, object)

    def __init__(self, ui_scale: UiScale) -> None:
        super().__init__()
        self._scale = ui_scale
        self._books: list[Book] = []
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
        self._list.itemClicked.connect(self._on_list_item_clicked)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_list_context_menu)

        self._stack.addWidget(self._grid_scroll)
        self._stack.addWidget(self._list)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._stack)

    def set_grid_mode(self) -> None:
        self._stack.setCurrentIndex(0)

    def set_list_mode(self) -> None:
        self._stack.setCurrentIndex(1)

    def is_grid_mode(self) -> bool:
        return self._stack.currentIndex() == 0

    def toggle_mode(self) -> None:
        if self.is_grid_mode():
            self.set_list_mode()
            return
        self.set_grid_mode()

    def populate(self, books: list[Book]) -> None:
        self._books = list(books)
        self._populate_grid(self._books)
        self._populate_list(self._books)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._books:
            self._populate_grid(self._books)

    def _populate_grid(self, books: list[Book]) -> None:
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        viewport_width = max(self._grid_scroll.viewport().width(), self._scale.card_w + 40)
        columns = max(1, viewport_width // (self._scale.card_w + self._scale.spacing + 8))
        usable_width = max(140, viewport_width - 24 - (columns - 1) * self._scale.spacing)
        card_width = max(140, min(int(usable_width / columns), self._scale.card_w + 40))
        card_height = int(card_width * 1.45)
        cover_height = int(card_height * 0.72)

        for idx, book in enumerate(books):
            row, col = divmod(idx, columns)
            self._grid_layout.addWidget(self._build_book_card(book, card_width, card_height, cover_height), row, col)

        add_row, add_col = divmod(len(books), columns)
        self._grid_layout.addWidget(self._build_add_card(card_width, card_height), add_row, add_col)
        self._grid_layout.setRowStretch(add_row + 1, 1)

    def _build_book_card(self, book: Book, card_w: int, card_h: int, cover_h: int) -> QWidget:
        card = _ClickableFrame() if book.file_path else QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        card.setFixedSize(card_w, card_h)
        card.setStyleSheet("QFrame { background-color: #ffffff; border: 1px solid #d0dae5; border-radius: 8px; } QFrame:hover { border-color: #7b9cc0; }")
        if book.file_path and isinstance(card, _ClickableFrame):
            card.clicked.connect(lambda _checked=False, path=book.file_path: self.openRequested.emit(path))
            card.contextRequested.connect(lambda pos, path=book.file_path: self.manageRequested.emit(path, pos))

        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 8, 8, 8)

        cover = QLabel("封面")
        cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover.setFixedHeight(cover_h)
        cover.setStyleSheet("background-color: #dae3f1; border-radius: 6px; color: #52616b; font-weight: bold;")
        if book.cover_path:
            pix = QPixmap(book.cover_path)
            if not pix.isNull():
                cover.setPixmap(pix.scaled(cover.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                cover.setText("")

        title = QLabel(book.title)
        title.setWordWrap(True)
        title.setFont(QFont("Microsoft YaHei UI", 10, QFont.Weight.Bold))
        title.setStyleSheet("color: #1a2333;")

        author = QLabel(book.author)
        author.setStyleSheet("color: #52616b;")

        layout.addWidget(cover)
        layout.addWidget(title)
        layout.addWidget(author)
        return card

    def _build_add_card(self, card_w: int, card_h: int) -> QWidget:
        card = _ClickableFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        card.setFixedSize(card_w, card_h)
        card.clicked.connect(self.addRequested)

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
            if book.file_path:
                item.setData(Qt.ItemDataRole.UserRole, book.file_path)
            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(8, 6, 8, 6)

            cover = QLabel()
            cover.setFixedSize(36, 52)
            cover.setStyleSheet("background-color: #dae3f1; border-radius: 4px;")
            if book.cover_path:
                pix = QPixmap(book.cover_path)
                if not pix.isNull():
                    cover.setPixmap(pix.scaled(cover.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

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
        add_item.setData(Qt.ItemDataRole.UserRole, "add")
        add_widget = QLabel("+ 添加书籍")
        add_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        add_widget.setStyleSheet("padding: 10px; color: #4f6d7a; border: 1px dashed #88a3b9;")
        add_item.setSizeHint(add_widget.sizeHint())
        self._list.addItem(add_item)
        self._list.setItemWidget(add_item, add_widget)

    def _on_list_item_clicked(self, item: QListWidgetItem) -> None:
        if item.data(Qt.ItemDataRole.UserRole) == "add":
            self.addRequested.emit()
            return

        file_path = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(file_path, str) and file_path:
            self.openRequested.emit(file_path)

    def _on_list_context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        file_path = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(file_path, str) and file_path and file_path != "add":
            self.manageRequested.emit(file_path, self._list.mapToGlobal(pos))


class _ClickableFrame(QFrame):
    """Simple clickable frame used by add-book card."""

    clicked = pyqtSignal()
    contextRequested = pyqtSignal(object)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def contextMenuEvent(self, event) -> None:  # type: ignore[override]
        self.contextRequested.emit(event.globalPos())
        event.accept()
