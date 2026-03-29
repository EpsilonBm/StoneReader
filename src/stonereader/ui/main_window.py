"""Main window for bookshelf in Iteration 1."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..services.library_service import LibraryService
from ..utils.screen import detect_ui_scale
from .bookshelf_view import BookshelfView
from .sidebar import Sidebar


class MainWindow(QMainWindow):
    """StoneReader bookshelf window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("StoneReader")

        self._library = LibraryService()
        self._scope = "shelf"
        self._selected_tag = ""
        self._ui_scale = detect_ui_scale()

        self.resize(int(self._ui_scale.width * 0.82), int(self._ui_scale.height * 0.84))
        self.setMinimumSize(980, 620)
        self._build_ui()
        self._reload_books()
        self._apply_style()

    def _build_ui(self) -> None:
        shell = QWidget()
        root = QVBoxLayout(shell)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        root.addLayout(self._build_toolbar())

        split = QSplitter()

        self._sidebar = Sidebar()
        self._sidebar.set_tags(self._library.all_tags())
        self._sidebar.scopeChanged.connect(self._on_scope_changed)

        self._bookshelf = BookshelfView(self._ui_scale)

        split.addWidget(self._sidebar)
        split.addWidget(self._bookshelf)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([240, 900])

        root.addWidget(split)
        self.setCentralWidget(shell)

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()

        title = QLabel("我的书架")
        title.setObjectName("pageTitle")

        self._sort_combo = QComboBox()
        self._sort_combo.addItems(["阅读时间", "添加时间", "书名", "作者"])
        self._sort_combo.currentIndexChanged.connect(self._reload_books)

        self._grid_btn = QPushButton("网格")
        self._list_btn = QPushButton("列表")
        self._add_book_btn = QPushButton("添加书籍")

        self._grid_btn.clicked.connect(self._bookshelf.set_grid_mode)
        self._list_btn.clicked.connect(self._bookshelf.set_list_mode)

        bar.addWidget(title)
        bar.addStretch(1)
        bar.addWidget(QLabel("排序"))
        bar.addWidget(self._sort_combo)
        bar.addWidget(self._grid_btn)
        bar.addWidget(self._list_btn)
        bar.addWidget(self._add_book_btn)

        return bar

    def _on_scope_changed(self, scope: str, tag: str) -> None:
        self._scope = scope
        self._selected_tag = tag
        self._reload_books()

    def _reload_books(self) -> None:
        sort_map = {
            0: "reading",
            1: "added",
            2: "title",
            3: "author",
        }
        books = self._library.query(
            scope=self._scope,
            sort_by=sort_map.get(self._sort_combo.currentIndex(), "title"),
            selected_tag=self._selected_tag,
        )
        self._bookshelf.populate(books)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow { background: #f2f4f7; }
            QLabel#pageTitle { font: 700 22px 'Microsoft YaHei UI'; color: #1f2a44; }
            QTreeWidget {
                background: #ffffff;
                border: 1px solid #d6deea;
                border-radius: 10px;
                padding: 6px;
                font: 14px 'Microsoft YaHei UI';
            }
            QPushButton, QComboBox {
                min-height: 30px;
                padding: 2px 10px;
                border: 1px solid #c6d2e1;
                border-radius: 8px;
                background: #ffffff;
            }
            QPushButton:hover {
                background: #eaf2fb;
            }
            QListWidget {
                background: #ffffff;
                border: 1px solid #d6deea;
                border-radius: 10px;
            }
            QScrollArea {
                border: 1px solid #d6deea;
                border-radius: 10px;
                background: #ffffff;
            }
            """
        )
