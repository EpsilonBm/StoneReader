"""Main window for bookshelf in Iteration 1."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..services.library_service import LibraryService
from ..utils.screen import detect_ui_scale
from .bookshelf_view import BookshelfView
from .reader_view import ReaderView
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

        self._stack = QStackedWidget()
        self._shelf_page = self._build_shelf_page()

        self._reader = ReaderView()
        self._reader.backRequested.connect(self._back_to_shelf)
        self._reader.progressChanged.connect(self._library.update_progress)

        self._stack.addWidget(self._shelf_page)
        self._stack.addWidget(self._reader)
        self._stack.setCurrentWidget(self._shelf_page)

        root.addWidget(self._stack)
        self.setCentralWidget(shell)

    def _build_shelf_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        self._bookshelf = BookshelfView(self._ui_scale)
        self._bookshelf.addRequested.connect(self._import_books)
        self._bookshelf.openRequested.connect(self._open_book)
        root.addLayout(self._build_toolbar())

        split = QSplitter()

        self._sidebar = Sidebar()
        self._sidebar.set_tags(self._library.all_tags())
        self._sidebar.scopeChanged.connect(self._on_scope_changed)

        split.addWidget(self._sidebar)
        split.addWidget(self._bookshelf)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([240, 900])

        root.addWidget(split)
        return page

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()

        title = QLabel("我的书架")
        title.setObjectName("pageTitle")

        self._sort_combo = QComboBox()
        self._sort_combo.addItems(["阅读时间", "添加时间", "书名", "作者"])
        self._sort_combo.currentIndexChanged.connect(self._reload_books)

        self._view_mode_btn = QPushButton("切换到列表")
        self._add_book_btn = QPushButton("添加书籍")

        self._view_mode_btn.clicked.connect(self._toggle_view_mode)
        self._add_book_btn.clicked.connect(self._import_books)

        bar.addWidget(title)
        bar.addStretch(1)
        bar.addWidget(QLabel("排序"))
        bar.addWidget(self._sort_combo)
        bar.addWidget(self._view_mode_btn)
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

    def _toggle_view_mode(self) -> None:
        self._bookshelf.toggle_mode()
        self._sync_view_mode_button()

    def _sync_view_mode_button(self) -> None:
        if self._bookshelf.is_grid_mode():
            self._view_mode_btn.setText("切换到列表")
            return
        self._view_mode_btn.setText("切换到网格")

    def _import_books(self) -> None:
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "导入书籍",
            "",
            "Books (*.txt *.epub *.mobi *.azw3);;All Files (*.*)",
        )
        if not file_paths:
            return

        added_count = self._library.import_books(file_paths)
        self._sidebar.set_tags(self._library.all_tags())
        self._reload_books()

        if added_count == 0:
            QMessageBox.information(self, "导入结果", "未导入新书籍（可能已存在）。")
            return
        QMessageBox.information(self, "导入结果", f"成功导入 {added_count} 本书籍。")

    def _open_book(self, file_path: str) -> None:
        book = self._library.get_by_path(file_path)
        if book is None:
            QMessageBox.warning(self, "打开失败", "未找到书籍记录。")
            return

        self._reader.load_book(book)
        self._stack.setCurrentWidget(self._reader)

    def _back_to_shelf(self) -> None:
        self._reload_books()
        self._stack.setCurrentWidget(self._shelf_page)

    def _apply_style(self) -> None:
        self._sync_view_mode_button()
        self.setStyleSheet(
            """
            QMainWindow {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #eef3f8, stop:1 #dfe8f4);
                color: #1f2a44;
            }
            QLabel#pageTitle { font: 700 22px 'Microsoft YaHei UI'; color: #1f2a44; }
            QLabel { color: #2b395b; }
            QTreeWidget {
                background: rgba(255, 255, 255, 0.92);
                border: 1px solid #c8d7e9;
                border-radius: 10px;
                padding: 6px;
                font: 14px 'Microsoft YaHei UI';
                color: #22324d;
            }
            QTreeWidget::item {
                padding: 4px 6px;
                border-radius: 6px;
                color: #22324d;
            }
            QTreeWidget::item:selected {
                background: #dbe8fb;
                color: #1a2740;
            }
            QPushButton, QComboBox {
                min-height: 30px;
                padding: 4px 14px;
                border: 1px solid #86a4c8;
                border-radius: 4px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #fefeff, stop:1 #eef4ff);
                color: #213455;
                font: 600 13px 'Microsoft YaHei UI';
            }
            QPushButton:hover, QComboBox:hover {
                background: #e5f0ff;
                border-color: #5f88bb;
            }
            QPushButton:pressed, QComboBox:pressed {
                background: #d6e7ff;
            }
            QComboBox::drop-down {
                border-left: 1px solid #c8d7e9;
                width: 24px;
                background: transparent;
            }
            QComboBox QAbstractItemView {
                border: 1px solid #86a4c8;
                border-radius: 4px;
                background: #fefeff;
                color: #213455;
                outline: none;
                selection-background-color: #dbe8fb;
                selection-color: #1a2740;
            }
            QComboBox QAbstractItemView::item {
                min-height: 28px;
                padding: 4px 8px;
            }
            QListWidget {
                background: rgba(255, 255, 255, 0.95);
                border: 1px solid #c8d7e9;
                border-radius: 8px;
                color: #22324d;
            }
            QScrollArea {
                border: 1px solid #c8d7e9;
                border-radius: 8px;
                background: rgba(255, 255, 255, 0.95);
            }
            """
        )
