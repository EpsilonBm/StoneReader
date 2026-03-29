"""TXT reader view for Iteration 2."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QComboBox,
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
from ..utils.text_chapters import ChapterSpan, detect_chapters


@dataclass(slots=True)
class ReaderVisualSettings:
    font_size: int = 18
    line_spacing_percent: int = 150
    line_width_percent: int = 82
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

        self._line_width = QSpinBox()
        self._line_width.setRange(55, 100)
        self._line_width.setSuffix("%")
        self._line_width.setValue(settings.line_width_percent)

        self._text_color = QLineEdit(settings.text_color)
        self._bg_color = QLineEdit(settings.background_color)

        root.addLayout(self._row("字号", self._font_size))
        root.addLayout(self._row("行距", self._line_spacing))
        root.addLayout(self._row("行长度", self._line_width))
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
            line_width_percent=self._line_width.value(),
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
        self._plain_text = ""
        self._chapters: list[ChapterSpan] = [ChapterSpan("全文", 0, 0)]
        self._syncing = False
        self._syncing_chapter = False
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
        self._chapter_combo = QComboBox()
        self._chapter_combo.setMinimumWidth(220)
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索当前文本")
        self._search_btn = QPushButton("搜索")
        self._next_btn = QPushButton("下一个")
        self._settings_btn = QPushButton("显示设置")

        self._back_btn.clicked.connect(self.backRequested)
        self._chapter_combo.currentIndexChanged.connect(self._jump_to_chapter)
        self._search_input.returnPressed.connect(self._search_all)
        self._search_btn.clicked.connect(self._search_all)
        self._next_btn.clicked.connect(self._goto_next_match)
        self._settings_btn.clicked.connect(self._open_settings_dialog)
        self._next_btn.setEnabled(False)

        toolbar.addWidget(self._back_btn)
        toolbar.addWidget(self._title_label, 1)
        toolbar.addWidget(self._chapter_combo)
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
            self._plain_text = ""
            self._text.setPlainText("该书籍没有关联本地文件路径。")
            self._set_chapters([ChapterSpan("全文", 0, 0)])
            return

        path = Path(book.file_path)
        if path.suffix.lower() != ".txt":
            self._plain_text = ""
            self._text.setPlainText("当前仅支持 TXT 阅读。请在后续迭代中打开该格式。")
            self._set_chapters([ChapterSpan("全文", 0, 0)])
            return

        content = self._read_text(path)
        self._plain_text = content
        self._text.setPlainText(content)
        self._set_chapters(detect_chapters(content))
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
        self._sync_chapter_combo_by_viewport()
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

        self._sync_chapter_combo_by_viewport()
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

        chapter = self._current_chapter()
        base_start = chapter.start
        base_end = chapter.end

        doc = self._text.document()
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#ffe08a"))

        extras = []
        for found in re.finditer(re.escape(term), self._plain_text[base_start:base_end], flags=re.IGNORECASE):
            start = base_start + found.start()
            end = base_start + found.end()
            self._matches.append((start, end))

            cursor = QTextCursor(doc)
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            extra = QTextEdit.ExtraSelection()
            extra.cursor = cursor
            extra.format = fmt
            extras.append(extra)

        self._text.setExtraSelections(extras)
        self._next_btn.setEnabled(bool(self._matches))
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
        self._next_btn.setEnabled(False)

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

        self._text.setLineWrapMode(QTextEdit.LineWrapMode.FixedPixelWidth)
        self._update_line_wrap_width()

        self._text.setStyleSheet(
            f"QTextEdit {{ color: {settings.text_color}; background: {settings.background_color}; border-radius: 10px; border: 1px solid #c8d7e9; }}"
        )

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._update_line_wrap_width()

    def _update_line_wrap_width(self) -> None:
        viewport_width = max(400, self._text.viewport().width())
        wrapped = max(260, int(viewport_width * self._visual_settings.line_width_percent / 100))
        self._text.setLineWrapColumnOrWidth(wrapped)

    def _set_chapters(self, chapters: list[ChapterSpan]) -> None:
        self._chapters = chapters or [ChapterSpan("全文", 0, len(self._plain_text))]
        self._syncing_chapter = True
        self._chapter_combo.clear()
        for chapter in self._chapters:
            self._chapter_combo.addItem(chapter.title)
        self._chapter_combo.setCurrentIndex(0)
        self._syncing_chapter = False

    def _current_chapter(self) -> ChapterSpan:
        idx = self._chapter_combo.currentIndex()
        if idx < 0 or idx >= len(self._chapters):
            return ChapterSpan("全文", 0, len(self._plain_text))
        return self._chapters[idx]

    def _jump_to_chapter(self, index: int) -> None:
        if self._syncing_chapter:
            return
        if index < 0 or index >= len(self._chapters):
            return

        chapter = self._chapters[index]
        cursor = self._text.textCursor()
        cursor.setPosition(chapter.start)
        self._text.setTextCursor(cursor)
        self._text.ensureCursorVisible()

    def _sync_chapter_combo_by_viewport(self) -> None:
        if not self._chapters:
            return

        cursor = self._text.cursorForPosition(QPoint(6, 6))
        pos = cursor.position()
        target_idx = 0
        for idx, chapter in enumerate(self._chapters):
            if chapter.start <= pos < chapter.end:
                target_idx = idx
                break

        if self._chapter_combo.currentIndex() != target_idx:
            self._syncing_chapter = True
            self._chapter_combo.setCurrentIndex(target_idx)
            self._syncing_chapter = False
