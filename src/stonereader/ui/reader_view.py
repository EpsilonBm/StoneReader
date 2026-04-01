"""TXT reader view for Iteration 2."""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from pathlib import Path
import re

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor, QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QFontComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
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
    font_family: str = "Microsoft YaHei UI"
    font_size: int = 18
    line_spacing_percent: int = 150
    line_width_percent: int = 82
    text_color: str = "#1f2a44"
    background_color: str = "#f8f5ee"


class HoverButton(QPushButton):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setMouseTracking(True)
        self.setStyleSheet("background: transparent; color: transparent; border: none;")

    def enterEvent(self, event):
        self.setStyleSheet("background: rgba(0, 0, 0, 0.08); color: #1f2a44; border-radius: 4px; font-weight: bold;")
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet("background: transparent; color: transparent; border: none;")
        super().leaveEvent(event)


class ReaderSettingsPanel(QWidget):
    """Side panel for reader text visual settings."""

    settingsChanged = pyqtSignal(ReaderVisualSettings)

    def __init__(self, settings: ReaderVisualSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SettingsPanel")
        self.setMaximumWidth(280)
        self._settings = ReaderVisualSettings(
            font_family=settings.font_family,
            font_size=settings.font_size,
            line_spacing_percent=settings.line_spacing_percent,
            text_color=settings.text_color,
            background_color=settings.background_color,
            line_width_percent=settings.line_width_percent,
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)

        title = QLabel("显示设置")
        title.setStyleSheet("font-weight: bold; font-size: 16px;")
        root.addWidget(title)

        self._font_family = QFontComboBox()
        self._font_family.setCurrentFont(QFont(settings.font_family))
        self._font_family.currentFontChanged.connect(self._on_changed)

        self._font_size = QSpinBox()
        self._font_size.setRange(12, 40)
        self._font_size.setValue(settings.font_size)
        self._font_size.valueChanged.connect(self._on_changed)

        self._line_spacing = QSpinBox()
        self._line_spacing.setRange(110, 260)
        self._line_spacing.setSingleStep(10)
        self._line_spacing.setSuffix("%")
        self._line_spacing.setValue(settings.line_spacing_percent)
        self._line_spacing.valueChanged.connect(self._on_changed)

        self._line_width = QSpinBox()
        self._line_width.setRange(50, 100)
        self._line_width.setSuffix("%")
        self._line_width.setValue(settings.line_width_percent)
        self._line_width.valueChanged.connect(self._on_changed)

        self._text_color_btn = QPushButton("选择色彩")
        self._update_color_btn(self._text_color_btn, self._settings.text_color)
        self._text_color_btn.clicked.connect(self._pick_text_color)

        self._bg_color_btn = QPushButton("选择色彩")
        self._update_color_btn(self._bg_color_btn, self._settings.background_color)
        self._bg_color_btn.clicked.connect(self._pick_bg_color)

        root.addLayout(self._row("字体格式", self._font_family))
        root.addLayout(self._row("字体大小", self._font_size))
        root.addLayout(self._row("行距比例", self._line_spacing))
        root.addLayout(self._row("居中部分", self._line_width))
        root.addLayout(self._row("文字颜色", self._text_color_btn))
        root.addLayout(self._row("背景颜色", self._bg_color_btn))
        root.addStretch(1)

        self.setStyleSheet("QWidget#SettingsPanel { border-left: 1px solid rgba(0,0,0,0.1); background: #ffffff; color: #1a2333; }")

    @staticmethod
    def _row(label: str, field: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        row.addWidget(field, 1)
        return row

    def _update_color_btn(self, btn: QPushButton, hex_color: str):
        color = QColor(hex_color)
        calc_text = 'white' if color.lightness() < 128 else 'black'
        btn.setStyleSheet(f"background-color: {hex_color}; color: {calc_text}; border: 1px solid #ccc; border-radius: 4px; padding: 4px;")

    def _pick_text_color(self):
        color = QColorDialog.getColor(QColor(self._settings.text_color), self, "选择文字颜色")
        if color.isValid():
            self._settings.text_color = color.name()
            self._update_color_btn(self._text_color_btn, color.name())
            self._on_changed()

    def _pick_bg_color(self):
        color = QColorDialog.getColor(QColor(self._settings.background_color), self, "选择背景颜色")
        if color.isValid():
            self._settings.background_color = color.name()
            self._update_color_btn(self._bg_color_btn, color.name())
            self._on_changed()

    def _on_changed(self, *_):
        self._settings.font_family = self._font_family.currentFont().family()
        self._settings.font_size = self._font_size.value()
        self._settings.line_spacing_percent = self._line_spacing.value()
        self._settings.line_width_percent = self._line_width.value()
        self.settingsChanged.emit(self._settings)


class SearchPanel(QWidget):
    """Floating search panel."""
    searchRequested = pyqtSignal(str)
    matchSelected = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SearchPanel")
        self.setMinimumWidth(320)
        self.setMinimumHeight(400)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("搜索全文...")
        self.input.returnPressed.connect(self._do_search)
        self._btn = QPushButton("搜索")
        self._btn.clicked.connect(self._do_search)

        row.addWidget(self.input, 1)
        row.addWidget(self._btn)

        self._results = QListWidget()
        self._results.itemClicked.connect(self._on_result_clicked)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.hide)

        layout.addLayout(row)
        layout.addWidget(QLabel("搜索结果 (单击跳转):"))
        layout.addWidget(self._results, 1)
        layout.addWidget(close_btn)

        self.setStyleSheet("""
            QWidget#SearchPanel {
                background: white;
                border: 1px solid #c8d7e9;
                border-radius: 8px;
            }
            QLineEdit, QPushButton {
                padding: 4px;
                border-radius: 4px;
                border: 1px solid #ccc;
            }
            QListWidget {
                border: 1px solid #ccc;
                border-radius: 4px;
            }
        """)
        self.hide()

    def set_results(self, matches: list[tuple[int, int, str]]):
        self._results.clear()
        if not matches:
            self._results.addItem("未找到结果。")
            return

        for start, end, context_html in matches:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, (start, end))
            
            label = QLabel(context_html)
            label.setWordWrap(True)
            label.setStyleSheet("padding: 6px; border-bottom: 1px solid #ebebeb; background: transparent;")
            
            item.setSizeHint(label.sizeHint())
            self._results.addItem(item)
            self._results.setItemWidget(item, label)

    def _do_search(self):
        term = self.input.text().strip()
        if term:
            self.searchRequested.emit(term)

    def _on_result_clicked(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            self.matchSelected.emit(data[0], data[1])


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
        self._visual_settings = ReaderVisualSettings()

        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.reading_area = QWidget()
        reading_layout = QVBoxLayout(self.reading_area)
        reading_layout.setContentsMargins(12, 12, 12, 12)
        reading_layout.setSpacing(0)

        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)

        self._back_btn = HoverButton("返回书架")
        self._back_btn.setFixedSize(90, 36)
        self._back_btn.clicked.connect(self.backRequested)

        self._header_info = QLabel("未打开书籍")
        self._header_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._header_info.setStyleSheet("color: rgba(0, 0, 0, 0.4); font-size: 13px;")

        self._toggle_settings_btn = QPushButton("≡ 显示设置")
        self._toggle_settings_btn.setStyleSheet("background: rgba(0,0,0,0.05); color: rgba(0,0,0,0.6); border: none; border-radius: 4px;")
        self._toggle_settings_btn.setFixedSize(100, 36)
        self._toggle_settings_btn.clicked.connect(self._toggle_settings)

        top_bar.addWidget(self._back_btn)
        top_bar.addWidget(self._header_info, 1)
        top_bar.addWidget(self._toggle_settings_btn)

        text_container = QWidget()
        text_layout = QHBoxLayout(text_container)
        text_layout.setContentsMargins(0, 10, 0, 10)
        text_layout.setSpacing(0)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setFrameShape(QFrame.Shape.NoFrame)
        self._text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._text.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)

        text_layout.addWidget(self._text, 1)

        bottom_bar = QHBoxLayout()
        bottom_bar.setContentsMargins(20, 10, 20, 10)

        self._chapter_combo = QComboBox()
        self._chapter_combo.setMinimumWidth(150)
        self._chapter_combo.setStyleSheet("background: rgba(255,255,255,0.7); color: rgba(0,0,0,0.8); border: none; border-radius: 4px; padding: 4px;")
        self._chapter_combo.currentIndexChanged.connect(self._jump_to_chapter)

        self._progress_slider = QSlider(Qt.Orientation.Horizontal)
        self._progress_slider.setRange(0, 1000)
        self._progress_slider.setStyleSheet("QSlider::handle:horizontal { background: rgba(0,0,0,0.3); width: 8px; border-radius: 4px; margin: -5px 0; } QSlider::groove:horizontal { background: rgba(0,0,0,0.1); height: 4px; border-radius: 2px; }")
        self._progress_slider.valueChanged.connect(self._on_slider_changed)

        self._progress_label = QLabel("0%")
        self._progress_label.setStyleSheet("color: rgba(0,0,0,0.5);")

        bottom_bar.addWidget(self._chapter_combo)
        bottom_bar.addSpacing(16)
        bottom_bar.addWidget(self._progress_slider, 1)
        bottom_bar.addSpacing(12)
        bottom_bar.addWidget(self._progress_label)

        reading_layout.addLayout(top_bar)
        reading_layout.addWidget(text_container, 1)
        reading_layout.addLayout(bottom_bar)

        self._settings_panel = ReaderSettingsPanel(self._visual_settings)
        self._settings_panel.settingsChanged.connect(self._apply_visual_settings)
        self._settings_panel.hide()

        self.main_layout.addWidget(self.reading_area, 1)
        self.main_layout.addWidget(self._settings_panel, 0)

        self._search_panel = SearchPanel(self.reading_area)
        self._search_panel.searchRequested.connect(self._perform_search)
        self._search_panel.matchSelected.connect(self._goto_match)

        # Ctrl+F
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self._toggle_search)

        self._apply_visual_settings(self._visual_settings)

    def _toggle_settings(self) -> None:
        self._settings_panel.setVisible(not self._settings_panel.isVisible())

    def _toggle_search(self) -> None:
        if self._search_panel.isVisible():
            self._search_panel.hide()
            self._text.setExtraSelections([])
        else:
            self._search_panel.show()
            self._search_panel.raise_()
            self._reposition_search_panel()
            self._search_panel.input.setFocus()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_line_wrap_width()
        if self._search_panel.isVisible():
            self._reposition_search_panel()

    def _reposition_search_panel(self) -> None:
        w = self.reading_area.width()
        self._search_panel.setGeometry(w - 340, 50, 320, 450)

    def load_book(self, book: Book) -> None:
        self._book = book
        self._set_header_text()
        self._plain_text = ""
        self._text.clear()

        if not book.file_path:
            self._text.setPlainText("该书籍没有关联本地文件路径。")
            self._set_chapters([ChapterSpan("全文", 0, 0)])
            return

        path = Path(book.file_path)
        if path.suffix.lower() != ".txt":
            self._text.setPlainText("当前仅支持 TXT 阅读。请在后续迭代中打开该格式。")
            self._set_chapters([ChapterSpan("全文", 0, 0)])
            return

        content = self._read_text(path)
        
        # Optimize text layout with ideographic spaces and proper newline blocks
        cleaned = []
        for line in content.splitlines():
            s = line.strip()
            if s:
                cleaned.append("　　" + s)
            else:
                cleaned.append("")
        self._plain_text = "\n".join(cleaned)

        self._text.setPlainText(self._plain_text)
        self._set_chapters(detect_chapters(self._plain_text))
        self._set_progress(book.read_progress)
        self._apply_visual_settings(self._visual_settings)

    def _read_text(self, path: Path) -> str:
        for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk"):
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
        self._sync_chapter_fast()
        self._progress_label.setText(f"{int(ratio * 100)}%")
        if self._book and self._book.file_path:
            self.progressChanged.emit(self._book.file_path, ratio)

    def _on_scroll_changed(self, value: int) -> None:
        if self._syncing:
            return

        scrollbar = self._text.verticalScrollBar()
        max_scroll = max(scrollbar.maximum(), 1)
        ratio = value / max_scroll if max_scroll > 0 else 0

        self._syncing = True
        self._progress_slider.setValue(int(ratio * 1000))
        self._syncing = False

        self._sync_chapter_fast()
        self._progress_label.setText(f"{int(ratio * 100)}%")
        if self._book and self._book.file_path:
            self.progressChanged.emit(self._book.file_path, ratio)

    def _set_progress(self, ratio: float) -> None:
        bounded = min(max(ratio, 0.0), 1.0)
        self._syncing = True
        self._progress_slider.setValue(int(bounded * 1000))
        self._syncing = False
        self._on_slider_changed(int(bounded * 1000))

    def _apply_visual_settings(self, settings: ReaderVisualSettings) -> None:
        self._visual_settings = settings

        # Save scroll ratio before modifying document
        scrollbar = self._text.verticalScrollBar()
        max_scroll = max(scrollbar.maximum(), 1)
        current_ratio = scrollbar.value() / max_scroll if max_scroll > 0 else 0

        self.reading_area.setStyleSheet(f"QWidget {{ background: {settings.background_color}; color: {settings.text_color}; }}")

        font = QFont(settings.font_family, settings.font_size)
        self._text.setFont(font)
        
        doc = self._text.document()
        if doc and doc.characterCount() > 0:
            cursor = QTextCursor(doc)
            cursor.select(QTextCursor.SelectionType.Document)
            block_format = cursor.blockFormat()
            # QTextBlockFormat.LineHeightTypes.ProportionalHeight is usually 1
            block_format.setLineHeight(settings.line_spacing_percent, 1) 
            block_format.setBottomMargin(settings.font_size * 0.8) 
            cursor.mergeBlockFormat(block_format)

        self._text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._update_line_wrap_width()

        # Restore scroll ratio
        new_max = max(scrollbar.maximum(), 1)
        self._syncing = True
        scrollbar.setValue(int(current_ratio * new_max))
        self._syncing = False

    def _update_line_wrap_width(self) -> None:
        max_w = self.reading_area.width()
        content_w = int(max_w * self._visual_settings.line_width_percent / 100)
        margin = max(0, (max_w - content_w) // 2)
        
        self._text.setStyleSheet(
            f"QTextEdit {{ "
            f"background: transparent; border: none; selection-background-color: #88a3b9; "
            f"padding-left: {margin}px; padding-right: {margin}px;"
            f"}}"
        )

    def _set_chapters(self, chapters: list[ChapterSpan]) -> None:
        self._chapters = chapters or [ChapterSpan("全文", 0, len(self._plain_text))]
        self._syncing_chapter = True
        self._chapter_combo.clear()
        for chapter in self._chapters:
            self._chapter_combo.addItem(chapter.title)
        self._chapter_combo.setCurrentIndex(0)
        self._syncing_chapter = False

    def _set_header_text(self, chapter_title: str = "") -> None:
        if not self._book:
            self._header_info.setText("未打开书籍")
            return
        
        # Calculate dynamic contrasting text color for header text
        color = QColor(self._visual_settings.text_color)
        self._header_info.setStyleSheet(f"color: {color.name()}; opacity: 0.5; font-size: 13px;")

        if chapter_title:
            self._header_info.setText(f"{self._book.title} - {chapter_title}")
        else:
            self._header_info.setText(self._book.title)

    def _sync_chapter_fast(self) -> None:
        if not self._chapters:
            return

        cursor = self._text.cursorForPosition(QPoint(10, 10))
        pos = cursor.position()

        starts = [c.start for c in self._chapters]
        idx = bisect.bisect_right(starts, pos) - 1
        idx = max(0, min(idx, len(self._chapters) - 1))

        cur_chapter = self._chapters[idx]
        self._set_header_text(cur_chapter.title)

        if self._chapter_combo.currentIndex() != idx:
            self._syncing_chapter = True
            self._chapter_combo.setCurrentIndex(idx)
            self._syncing_chapter = False

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

    def _perform_search(self, term: str) -> None:
        if not term or not self._plain_text:
            return

        doc = self._text.document()
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#ffe08a"))
        fmt.setForeground(QColor("#000000"))

        self._text.setExtraSelections([])

        matches = []
        extras = []
        import html
        for found in re.finditer(re.escape(term), self._plain_text, flags=re.IGNORECASE):
            start = found.start()
            end = found.end()

            ctx_start = max(0, start - 15)
            ctx_end = min(len(self._plain_text), end + 15)
            context_raw = "..." + self._plain_text[ctx_start:ctx_end].replace("\n", " ") + "..."
            
            context_html = html.escape(context_raw)
            escaped_term = html.escape(term)
            context_html = re.sub(
                f"({re.escape(escaped_term)})",
                r'<span style="background-color: #ffda6a; color: #000; font-weight: bold;">\1</span>',
                context_html,
                flags=re.IGNORECASE
            )

            matches.append((start, end, context_html))

            cursor = QTextCursor(doc)
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            extra = QTextEdit.ExtraSelection()
            extra.cursor = cursor
            extra.format = fmt
            extras.append(extra)

            if len(matches) > 100:
                break

        self._text.setExtraSelections(extras)
        self._search_panel.set_results(matches)

    def _goto_match(self, start: int, end: int) -> None:
        cursor = self._text.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self._text.setTextCursor(cursor)
        self._text.ensureCursorVisible()
