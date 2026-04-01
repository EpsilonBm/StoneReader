"""Main window for bookshelf in Iteration 1."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
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


class ToastMessage(QLabel):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("ToastMessage")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            "QLabel#ToastMessage {"
            "background: rgba(19, 29, 48, 0.92);"
            "color: #f8fbff;"
            "border: 1px solid rgba(255,255,255,0.16);"
            "border-radius: 8px;"
            "padding: 8px 14px;"
            "font: 600 13px 'Microsoft YaHei UI';"
            "}"
        )
        self.hide()

    def show_message(self, text: str, duration_ms: int = 1800) -> None:
        self.setText(text)
        self.adjustSize()
        parent = self.parentWidget()
        if parent is None:
            return
        margin = 18
        x = max(margin, parent.width() - self.width() - margin)
        y = margin
        self.move(x, y)
        self.show()
        self.raise_()
        QTimer.singleShot(duration_ms, self.hide)


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

    @staticmethod
    def _icon_path(name: str) -> str:
        root = Path(__file__).resolve().parents[3]
        return str(root / "source" / "icon" / f"{name}.svg")

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
        self._reader.annotationsChanged.connect(self._library.update_annotations)

        self._stack.addWidget(self._shelf_page)
        self._stack.addWidget(self._reader)
        self._stack.setCurrentWidget(self._shelf_page)

        root.addWidget(self._stack)
        self.setCentralWidget(shell)
        self._toast = ToastMessage(shell)

    def _build_shelf_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        self._bookshelf = BookshelfView(self._ui_scale)
        self._bookshelf.addRequested.connect(self._import_books)
        self._bookshelf.openRequested.connect(self._open_book)
        self._bookshelf.manageRequested.connect(self._show_book_manage_menu)
        self._bookshelf.actionRequested.connect(self._handle_book_action)
        root.addLayout(self._build_toolbar())

        split = QSplitter()

        self._sidebar = Sidebar()
        self._sidebar.set_formats(self._library.all_formats())
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
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(8)

        title = QLabel("我的书架")
        title.setObjectName("pageTitle")

        self._sort_combo = QComboBox()
        self._sort_combo.addItems(["阅读时间", "添加时间", "书名", "作者"])
        self._sort_combo.setFixedHeight(32)
        self._sort_combo.currentIndexChanged.connect(self._reload_books)

        self._view_mode_btn = QPushButton("")
        self._view_mode_btn.setIcon(QIcon(self._icon_path("view-list")))
        self._view_mode_btn.setToolTip("切换到列表")
        self._view_mode_btn.setFixedSize(36, 32)

        self._add_book_btn = QPushButton("")
        self._add_book_btn.setIcon(QIcon(self._icon_path("add")))
        self._add_book_btn.setToolTip("添加书籍")
        self._add_book_btn.setFixedSize(36, 32)

        self._view_mode_btn.clicked.connect(self._toggle_view_mode)
        self._add_book_btn.clicked.connect(self._import_books)

        bar.addWidget(title)
        bar.addStretch(1)
        sort_label = QLabel("排序")
        sort_label.setFixedHeight(32)
        sort_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        bar.addWidget(sort_label)
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
        self._bookshelf.populate(books, show_add=self._scope == "shelf")

    def _toggle_view_mode(self) -> None:
        self._bookshelf.toggle_mode()
        self._sync_view_mode_button()

    def _sync_view_mode_button(self) -> None:
        if self._bookshelf.is_grid_mode():
            self._view_mode_btn.setIcon(QIcon(self._icon_path("view-list")))
            self._view_mode_btn.setToolTip("切换到列表")
            return
        self._view_mode_btn.setIcon(QIcon(self._icon_path("view-grid")))
        self._view_mode_btn.setToolTip("切换到网格")

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
        self._sidebar.set_formats(self._library.all_formats())
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

    def _show_book_manage_menu(self, file_path: str, global_pos) -> None:
        book = self._library.get_by_path(file_path)
        if book is None:
            return

        menu = QMenu(self)
        add_tag = menu.addAction("添加标签")
        mark_read = menu.addAction("标记为已读" if not book.is_read else "取消已读")
        mark_fav = menu.addAction("标记最爱" if not book.is_favorite else "取消最爱")
        remove = menu.addAction("从书架删除")
        chosen = menu.exec(global_pos)
        if chosen is add_tag:
            text, ok = QInputDialog.getText(self, "添加标签", "输入自定义标签:")
            if ok and text.strip():
                self._library.add_custom_tag(file_path, text.strip())
                self._sidebar.set_tags(self._library.all_tags())
                self._reload_books()
        elif chosen is mark_read:
            self._library.set_read_status(file_path, not book.is_read)
            self._show_toast("已标记为已读" if not book.is_read else "已取消已读")
            self._reload_books()
        elif chosen is mark_fav:
            self._library.set_favorite_status(file_path, not book.is_favorite)
            self._show_toast("已添加到最爱" if not book.is_favorite else "已取消最爱")
            self._reload_books()
        elif chosen is remove:
            self._library.remove_book(file_path)
            self._sidebar.set_formats(self._library.all_formats())
            self._sidebar.set_tags(self._library.all_tags())
            self._reload_books()

    def _handle_book_action(self, file_path: str, action: str) -> None:
        book = self._library.get_by_path(file_path)
        if book is None:
            return

        if action == "tag":
            text, ok = QInputDialog.getText(self, "添加标签", "输入自定义标签:")
            if ok and text.strip():
                self._library.add_custom_tag(file_path, text.strip())
                self._sidebar.set_tags(self._library.all_tags())
        elif action == "read":
            self._library.set_read_status(file_path, not book.is_read)
            self._show_toast("已标记为已读" if not book.is_read else "已取消已读")
        elif action == "favorite":
            self._library.set_favorite_status(file_path, not book.is_favorite)
            self._show_toast("已添加到最爱" if not book.is_favorite else "已取消最爱")
        elif action == "delete":
            self._library.remove_book(file_path)
            self._sidebar.set_formats(self._library.all_formats())
            self._sidebar.set_tags(self._library.all_tags())

        self._reload_books()

    def _show_toast(self, text: str) -> None:
        if hasattr(self, "_toast"):
            self._toast.show_message(text)

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
                background: transparent;
            }
            QTreeWidget::item:hover { background: #e2e8f0; }
            QTreeWidget::item:selected {
                background: #dbe8fb;
                color: #1a2740;
            }
            QPushButton {
                min-height: 30px;
                padding: 4px 14px;
                border: none;
                border-radius: 4px;
                background: transparent;
                color: #213455;
                font: 600 13px 'Microsoft YaHei UI';
            }
            QPushButton:hover {
                background: #e5f0ff;
            }
            QPushButton:pressed {
                background: #d6e7ff;
            }
            QComboBox {
                min-height: 30px;
                padding: 4px 10px;
                border: 1px solid #86a4c8;
                border-radius: 4px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #fefeff, stop:1 #eef4ff);
                color: #213455;
                font: 600 13px 'Microsoft YaHei UI';
            }
            QComboBox:hover {
                background: #e5f0ff;
                border-color: #5f88bb;
            }
            QComboBox:pressed {
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
