"""TXT reader view for Iteration 2."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..models.book import Book


@dataclass(slots=True)
class ReaderVisualSettings:
    font_size: int = 18
    line_spacing_percent: int = 150
    text_color: str = "#1f2a44"
    background_color: str = "#f8f5ee"


class ReaderSettingsDialog(QDialog):
    """Dialog for reader text visual settings."""

    def __init__(self, settings: ReaderVisualSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("阅读显示设置")
        self._settings = ReaderVisualSettings(
            font_size=settings.font_size,
            line_spacing_percent=settings.line_spacing_percent,
            text_color=settings.text_color,
            background_color=settings.background_color,
        )

        root = QVBoxLayout(self)

        self._font_size = QSpinBox()
        self._font_size.setRange(12, 40)
        self._font_size.setValue(settings.font_size)

        self._line_spacing = QSpinBox()
        self._line_spacing.setRange(110, 260)
        self._line_spacing.setSingleStep(10)
        self._line_spacing.setSuffix("%")
        self._line_spacing.setValue(settings.line_spacing_percent)

        self._text_color = QLineEdit(settings.text_color)
        self._bg_color = QLineEdit(settings.background_color)

        root.addLayout(self._row("字号", self._font_size))
        root.addLayout(self._row("行距", self._line_spacing))
        root.addLayout(self._row("文字颜色", self._text_color))
        root.addLayout(self._row("背景颜色", self._bg_color))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _row(label: str, field: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        row.addWidget(field, 1)
        return row

    def values(self) -> ReaderVisualSettings:
        return ReaderVisualSettings(
            font_size=self._font_size.value(),
            line_spacing_percent=self._line_spacing.value(),
            text_color=self._text_color.text().strip() or "#1f2a44",
            background_color=self._bg_color.text().strip() or "#f8f5ee",
        )


class ReaderView(QWidget):
    """A simple TXT reading view with progress and search."""

    backRequested = pyqtSignal()
    progressChanged = pyqtSignal(str, float)

    def __init__(self) -> None:
        super().__init__()
        self._book: Book | None = None
        self._syncing = False
        self._matches: list[tuple[int, int]] = []
        self._active_match_index = -1
        self._visual_settings = ReaderVisualSettings()

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        toolbar = QHBoxLayout()
        self._back_btn = QPushButton("返回书架")
        self._title_label = QLabel("未打开书籍")
        self._title_label.setObjectName("readerTitle")
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索当前文本")
        self._search_btn = QPushButton("搜索")
        self._next_btn = QPushButton("下一个")
        self._settings_btn = QPushButton("显示设置")

        self._back_btn.clicked.connect(self.backRequested)
        self._search_btn.clicked.connect(self._search_all)
        self._next_btn.clicked.connect(self._goto_next_match)
        self._settings_btn.clicked.connect(self._open_settings_dialog)

        toolbar.addWidget(self._back_btn)
        toolbar.addWidget(self._title_label, 1)
        toolbar.addWidget(self._search_input, 2)
        toolbar.addWidget(self._search_btn)
        toolbar.addWidget(self._next_btn)
        toolbar.addWidget(self._settings_btn)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)

        bottom = QHBoxLayout()
        self._progress_slider = QSlider(Qt.Orientation.Horizontal)
        self._progress_slider.setRange(0, 1000)
        self._progress_slider.valueChanged.connect(self._on_slider_changed)
        self._progress_label = QLabel("0%")
        bottom.addWidget(self._progress_slider, 1)
        bottom.addWidget(self._progress_label)

        root.addLayout(toolbar)
        root.addWidget(self._text, 1)
        root.addLayout(bottom)

        self._apply_visual_settings(self._visual_settings)

    def load_book(self, book: Book) -> None:
        """Load a txt file into reader."""
        self._book = book
        self._title_label.setText(book.title)

        if not book.file_path:
            self._text.setPlainText("该书籍没有关联本地文件路径。")
            return

        path = Path(book.file_path)
        if path.suffix.lower() != ".txt":
            self._text.setPlainText("当前仅支持 TXT 阅读。请在后续迭代中打开该格式。")
            return

        content = self._read_text(path)
        self._text.setPlainText(content)
        self._clear_search_highlight()
        self._set_progress(book.read_progress)

    def _read_text(self, path: Path) -> str:
        for encoding in ("utf-8", "utf-8-sig", "gb18030"):
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
            except OSError as exc:
                return f"读取失败: {exc}"
        return "读取失败: 编码不受支持。"

    def _on_slider_changed(self, value: int) -> None:
        if self._syncing:
            return

        scrollbar = self._text.verticalScrollBar()
        max_scroll = max(scrollbar.maximum(), 1)
        target = int(value / 1000 * max_scroll)

        self._syncing = True
        scrollbar.setValue(target)
        self._syncing = False

        ratio = value / 1000
        self._progress_label.setText(f"{int(ratio * 100)}%")
        if self._book and self._book.file_path:
            self.progressChanged.emit(self._book.file_path, ratio)

    def _on_scroll_changed(self, value: int) -> None:
        if self._syncing:
            return

        scrollbar = self._text.verticalScrollBar()
        max_scroll = max(scrollbar.maximum(), 1)
        ratio = value / max_scroll

        self._syncing = True
        self._progress_slider.setValue(int(ratio * 1000))
        self._syncing = False

        self._progress_label.setText(f"{int(ratio * 100)}%")
        if self._book and self._book.file_path:
            self.progressChanged.emit(self._book.file_path, ratio)

    def _set_progress(self, ratio: float) -> None:
        bounded = min(max(ratio, 0.0), 1.0)
        self._syncing = True
        self._progress_slider.setValue(int(bounded * 1000))
        self._syncing = False
        self._on_slider_changed(int(bounded * 1000))

    def _search_all(self) -> None:
        term = self._search_input.text().strip()
        self._clear_search_highlight()
        if not term:
            return

        doc = self._text.document()
        cursor = QTextCursor(doc)
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#ffe08a"))

        extras = []
        while True:
            cursor = doc.find(term, cursor)
            if cursor.isNull():
                break
            self._matches.append((cursor.selectionStart(), cursor.selectionEnd()))
            extra = QTextEdit.ExtraSelection()
            extra.cursor = cursor
            extra.format = fmt
            extras.append(extra)

        self._text.setExtraSelections(extras)
        if not self._matches:
            QMessageBox.information(self, "搜索", "未找到匹配内容。")
            return

        self._active_match_index = -1
        self._goto_next_match()

    def _goto_next_match(self) -> None:
        if not self._matches:
            return

        self._active_match_index = (self._active_match_index + 1) % len(self._matches)
        start, end = self._matches[self._active_match_index]

        cursor = self._text.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self._text.setTextCursor(cursor)
        self._text.ensureCursorVisible()

    def _clear_search_highlight(self) -> None:
        self._matches.clear()
        self._active_match_index = -1
        self._text.setExtraSelections([])

    def _open_settings_dialog(self) -> None:
        dialog = ReaderSettingsDialog(self._visual_settings, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self._visual_settings = dialog.values()
        self._apply_visual_settings(self._visual_settings)

    def _apply_visual_settings(self, settings: ReaderVisualSettings) -> None:
        font = self._text.font()
        font.setPointSize(settings.font_size)
        self._text.setFont(font)

        cursor = self._text.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        block_format = cursor.blockFormat()
        block_format.setLineHeight(settings.line_spacing_percent, 1)
        cursor.mergeBlockFormat(block_format)
        cursor.clearSelection()
        self._text.setTextCursor(cursor)

        self._text.setStyleSheet(
            f"QTextEdit {{ color: {settings.text_color}; background: {settings.background_color}; border-radius: 10px; border: 1px solid #c8d7e9; }}"
        )
