"""Reader view supporting multiple modes and full features."""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
import html

from PyQt6.QtCore import QPoint, Qt, pyqtSignal, QSize
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor, QFont, QKeySequence, QShortcut, QIcon, QAction
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QColorDialog,
    QComboBox,
    QFontComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QKeySequenceEdit,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..models.book import Book
from ..utils.text_chapters import ChapterItem, parse_txt
from ..utils.epub_parser import parse_epub
from ..utils.mobi_parser import parse_mobi


@dataclass(slots=True)
class ReaderVisualSettings:
    font_family_zh: str = "霞鹜文楷"
    font_family_en: str = "Times New Roman"
    font_size: int = 18
    line_spacing_percent: int = 150
    line_width_percent: int = 82
    text_color: str = "#1f2a44"
    background_color: str = "#f8f5ee"
    reading_mode: str = "chapter_scroll"  # "full_scroll", "chapter_scroll", "paginated"
    shortcut_prev: str = "Left"
    shortcut_next: str = "Right"


class HoverButton(QPushButton):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setMouseTracking(True)
        self.setStyleSheet("background: transparent; color: transparent; border: none;")

    def enterEvent(self, event):
        self.setStyleSheet("background: rgba(0, 0, 0, 0.08); color: inherit; border-radius: 4px; font-weight: bold;")
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet("background: transparent; color: transparent; border: none;")
        super().leaveEvent(event)


def _icon_path(name: str) -> str:
    root = Path(__file__).resolve().parents[3]
    return str(root / "source" / "icon" / f"{name}.svg")


class SelectionQuickBar(QFrame):
    bookmarkClicked = pyqtSignal()
    highlightClicked = pyqtSignal()
    noteClicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SelectionQuickBar")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(
            "QFrame#SelectionQuickBar { background: rgba(255,255,255,0.96); border: 1px solid #cbd5e1; border-radius: 8px; }"
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(6, 6, 6, 6)
        row.setSpacing(4)

        self._btn_bm = QToolButton(self)
        self._btn_bm.setIcon(QIcon(_icon_path("bookmark")))
        self._btn_bm.setToolTip("添加书签")
        self._btn_bm.setIconSize(QSize(18, 18))
        self._btn_bm.clicked.connect(self.bookmarkClicked)

        self._btn_hl = QToolButton(self)
        self._btn_hl.setIcon(QIcon(_icon_path("highlight")))
        self._btn_hl.setToolTip("添加标记")
        self._btn_hl.setIconSize(QSize(18, 18))
        self._btn_hl.clicked.connect(self.highlightClicked)

        self._btn_note = QToolButton(self)
        self._btn_note.setIcon(QIcon(_icon_path("note")))
        self._btn_note.setToolTip("添加笔记")
        self._btn_note.setIconSize(QSize(18, 18))
        self._btn_note.clicked.connect(self.noteClicked)

        for btn in (self._btn_bm, self._btn_hl, self._btn_note):
            btn.setStyleSheet(
                "QToolButton { border: none; padding: 4px; border-radius: 6px; }"
                "QToolButton:hover { background: #e2e8f0; }"
            )
            row.addWidget(btn)

        self.hide()


class ReaderSettingsPanel(QWidget):
    """Side panel for reader text visual settings."""

    settingsChanged = pyqtSignal(ReaderVisualSettings)

    def __init__(self, settings: ReaderVisualSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SettingsPanel")
        self.setMinimumWidth(340)
        self.setMaximumWidth(360)
        self._settings = ReaderVisualSettings(
            font_family_zh=settings.font_family_zh,
            font_family_en=settings.font_family_en,
            font_size=settings.font_size,
            line_spacing_percent=settings.line_spacing_percent,
            text_color=settings.text_color,
            background_color=settings.background_color,
            line_width_percent=settings.line_width_percent,
            reading_mode=settings.reading_mode,
            shortcut_prev=settings.shortcut_prev,
            shortcut_next=settings.shortcut_next,
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)

        title = QLabel("显示设置")
        title.setStyleSheet("font-weight: bold; font-size: 16px;")
        root.addWidget(title)
        
        self._reading_mode = QComboBox()
        self._reading_mode.addItems(["全书滑动", "单章滑动", "翻页模式"])
        if settings.reading_mode == "full_scroll":
            self._reading_mode.setCurrentIndex(0)
        elif settings.reading_mode == "paginated":
            self._reading_mode.setCurrentIndex(2)
        else:
            self._reading_mode.setCurrentIndex(1)
        self._reading_mode.currentIndexChanged.connect(self._on_changed)

        self._font_family_zh = QFontComboBox()
        self._font_family_zh.setCurrentFont(QFont(settings.font_family_zh))
        self._font_family_zh.currentFontChanged.connect(self._on_changed)

        self._font_family_en = QFontComboBox()
        self._font_family_en.setCurrentFont(QFont(settings.font_family_en))
        self._font_family_en.currentFontChanged.connect(self._on_changed)

        self._font_size = QSpinBox()
        self._font_size.setRange(12, 40)
        self._font_size.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.PlusMinus)
        self._font_size.setMinimumHeight(32)
        self._font_size.setValue(settings.font_size)
        self._font_size.valueChanged.connect(self._on_changed)

        self._line_spacing = QSpinBox()
        self._line_spacing.setRange(110, 260)
        self._line_spacing.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.PlusMinus)
        self._line_spacing.setMinimumHeight(32)
        self._line_spacing.setSingleStep(10)
        self._line_spacing.setSuffix("%")
        self._line_spacing.setValue(settings.line_spacing_percent)
        self._line_spacing.valueChanged.connect(self._on_changed)

        self._line_width = QSpinBox()
        self._line_width.setRange(50, 100)
        self._line_width.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.PlusMinus)
        self._line_width.setMinimumHeight(32)
        self._line_width.setSuffix("%")
        self._line_width.setValue(settings.line_width_percent)
        self._line_width.valueChanged.connect(self._on_changed)

        self._text_color_btn = QPushButton("选择色彩")
        self._update_color_btn(self._text_color_btn, self._settings.text_color)
        self._text_color_btn.clicked.connect(self._pick_text_color)

        self._bg_color_btn = QPushButton("选择色彩")
        self._update_color_btn(self._bg_color_btn, self._settings.background_color)
        self._bg_color_btn.clicked.connect(self._pick_bg_color)

        self._shortcut_prev = QKeySequenceEdit(QKeySequence(settings.shortcut_prev))
        self._shortcut_prev.keySequenceChanged.connect(self._on_changed)
        
        self._shortcut_next = QKeySequenceEdit(QKeySequence(settings.shortcut_next))
        self._shortcut_next.keySequenceChanged.connect(self._on_changed)
        
        root.addLayout(self._row("阅读模式", self._reading_mode))
        root.addLayout(self._row("英文字体", self._font_family_en))
        root.addLayout(self._row("中文字体", self._font_family_zh))
        root.addLayout(self._row("字体大小", self._font_size))
        root.addLayout(self._row("行距比例", self._line_spacing))
        root.addLayout(self._row("居中部分", self._line_width))
        root.addLayout(self._row("文字颜色", self._text_color_btn))
        root.addLayout(self._row("背景颜色", self._bg_color_btn))
        root.addLayout(self._row("上章快捷键", self._shortcut_prev))
        root.addLayout(self._row("下章快捷键", self._shortcut_next))
        root.addStretch(1)

        self.setStyleSheet("""
            QWidget#SettingsPanel { border-left: 1px solid rgba(0,0,0,0.1); background: #ffffff; color: #1a2333; }
            QSpinBox, QComboBox, QFontComboBox, QKeySequenceEdit { background: #f2f4f7; color: #1a2333; border: 1px solid #c9d0d8; padding: 4px 8px; border-radius: 4px; }
            QSpinBox::up-button, QSpinBox::down-button { width: 26px; border: none; background: #e2e8f0; }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #cbd5e1; }
            QLabel { color: #1a2333; }
        """)

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
        self._settings.font_family_zh = self._font_family_zh.currentFont().family()
        self._settings.font_family_en = self._font_family_en.currentFont().family()
        self._settings.font_size = self._font_size.value()
        self._settings.line_spacing_percent = self._line_spacing.value()
        self._settings.line_width_percent = self._line_width.value()
        self._settings.shortcut_prev = self._shortcut_prev.keySequence().toString()
        self._settings.shortcut_next = self._shortcut_next.keySequence().toString()
        
        mode_idx = self._reading_mode.currentIndex()
        if mode_idx == 0:
            self._settings.reading_mode = "full_scroll"
        elif mode_idx == 2:
            self._settings.reading_mode = "paginated"
        else:
            self._settings.reading_mode = "chapter_scroll"
            
        self.settingsChanged.emit(self._settings)


class ReaderSidebar(QWidget):
    """Left sidebar for TOC, bookmarks, highlights and notes."""
    chapterSelected = pyqtSignal(int)
    annotationSelected = pyqtSignal(str, int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ReaderSidebar")
        self.setMaximumWidth(260)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        tabs_layout = QHBoxLayout()
        tabs_layout.setContentsMargins(8, 8, 8, 8)
        tabs_layout.setSpacing(6)

        self._btn_toc = QToolButton(self)
        self._btn_toc.setIcon(QIcon(_icon_path("toc")))
        self._btn_toc.setToolTip("目录")

        self._btn_bm = QToolButton(self)
        self._btn_bm.setIcon(QIcon(_icon_path("bookmark")))
        self._btn_bm.setToolTip("书签")

        self._btn_hl = QToolButton(self)
        self._btn_hl.setIcon(QIcon(_icon_path("highlight")))
        self._btn_hl.setToolTip("标记")

        self._btn_note = QToolButton(self)
        self._btn_note.setIcon(QIcon(_icon_path("note")))
        self._btn_note.setToolTip("笔记")

        for idx, btn in enumerate((self._btn_toc, self._btn_bm, self._btn_hl, self._btn_note)):
            btn.setIconSize(QSize(18, 18))
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.clicked.connect(lambda _checked, i=idx: self._switch_panel(i))
            tabs_layout.addWidget(btn)

        self._stack = QStackedWidget(self)
        self._toc_list = QListWidget()
        self._toc_list.itemClicked.connect(self._on_toc_clicked)

        self._bm_list = QListWidget()
        self._bm_list.itemClicked.connect(lambda item: self._emit_annotation("bookmark", item))

        self._hl_list = QListWidget()
        self._hl_list.itemClicked.connect(lambda item: self._emit_annotation("highlight", item))

        self._note_list = QListWidget()
        self._note_list.itemClicked.connect(lambda item: self._emit_annotation("note", item))

        self._stack.addWidget(self._toc_list)
        self._stack.addWidget(self._bm_list)
        self._stack.addWidget(self._hl_list)
        self._stack.addWidget(self._note_list)
        
        layout.addLayout(tabs_layout)
        layout.addWidget(self._stack)
        self._btn_toc.setChecked(True)

        self.setStyleSheet(
            "QWidget#ReaderSidebar { border-right: 1px solid rgba(0,0,0,0.1); background: #ffffff; color: #1a2333; }"
            "QListWidget { border: none; background: transparent; padding: 4px; }"
            "QListWidget::item { padding: 6px 8px; border-radius: 6px; }"
            "QListWidget::item:selected { background: #e2e8f0; }"
            "QToolButton { border: none; padding: 6px; border-radius: 6px; }"
            "QToolButton:checked, QToolButton:hover { background: #e2e8f0; }"
        )

    def _switch_panel(self, index: int) -> None:
        self._stack.setCurrentIndex(index)

    def populate_toc(self, chapters: list[ChapterItem]):
        self._toc_list.clear()
        for idx, ch in enumerate(chapters):
            item = QListWidgetItem(ch.title)
            item.setData(Qt.ItemDataRole.UserRole, idx)
            self._toc_list.addItem(item)
            
    def _on_toc_clicked(self, item: QListWidgetItem):
        idx = item.data(Qt.ItemDataRole.UserRole)
        self.chapterSelected.emit(idx)

    def populate_annotations(self, bookmarks: list[dict], highlights: list[dict], notes: list[dict]) -> None:
        self._fill_annotation_list(self._bm_list, bookmarks)
        self._fill_annotation_list(self._hl_list, highlights)
        self._fill_annotation_list(self._note_list, notes)

    def _fill_annotation_list(self, list_widget: QListWidget, records: list[dict]) -> None:
        list_widget.clear()
        for idx, rec in enumerate(records):
            preview = rec.get("preview", "")
            chapter = rec.get("chapter_title", "")
            text = f"{chapter} | {preview}" if chapter else preview
            item = QListWidgetItem(text[:120])
            item.setToolTip(text)
            item.setData(Qt.ItemDataRole.UserRole, idx)
            list_widget.addItem(item)

    def _emit_annotation(self, kind: str, item: QListWidgetItem) -> None:
        idx = item.data(Qt.ItemDataRole.UserRole)
        self.annotationSelected.emit(kind, idx)

class SearchPanel(QWidget):
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
        self.input.setPlaceholderText("搜索当前视图...")
        self.input.returnPressed.connect(self._do_search)
        self._btn = QPushButton("搜索")
        self._btn.clicked.connect(self._do_search)

        row.addWidget(self.input, 1)
        row.addWidget(self._btn)

        self._results = QListWidget()
        self._results.itemClicked.connect(self._on_result_clicked)

        close_btn = QPushButton("关闭搜索")
        close_btn.clicked.connect(self.hide)

        layout.addLayout(row)
        layout.addWidget(QLabel("搜索结果 (单击跳转):"))
        layout.addWidget(self._results, 1)
        layout.addWidget(close_btn)

        self.setStyleSheet("""QWidget#SearchPanel { background: white; border: 1px solid #c8d7e9; border-radius: 8px; }""")
        self.hide()

    def set_results(self, matches: list[tuple[int, int, str]]):
        self._results.clear()
        if not matches:
            label = QLabel("未找到结果。")
            item = QListWidgetItem()
            item.setSizeHint(label.sizeHint())
            self._results.addItem(item)
            self._results.setItemWidget(item, label)
            return
            
        for start, end, ctx in matches:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, (start, end))
            label = QLabel(ctx)
            label.setWordWrap(True)
            label.setStyleSheet("padding: 8px; border-bottom: 1px solid #ebebeb; background: transparent;")
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
    """Refactored Reader view for Iteration 3."""

    backRequested = pyqtSignal()
    progressChanged = pyqtSignal(str, float)
    annotationsChanged = pyqtSignal(str, list, list, list)

    def __init__(self) -> None:
        super().__init__()
        self._book: Book | None = None
        self._chapters: list[ChapterItem] = [ChapterItem("全文", "")]
        
        # State trackers
        self._syncing = False
        self._current_chapter_idx = 0
        self._visual_settings = ReaderVisualSettings()
        self._bookmarks: list[dict] = []
        self._highlights: list[dict] = []
        self._notes: list[dict] = []

        # Layout Setup
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # 1. Left Sidebar
        self._sidebar = ReaderSidebar()
        self._sidebar.chapterSelected.connect(self._jump_to_chapter)
        self._sidebar.annotationSelected.connect(self._jump_to_annotation)
        self._sidebar.hide()

        # 2. Central Reading Area
        self.reading_area = QWidget()
        reading_layout = QVBoxLayout(self.reading_area)
        reading_layout.setContentsMargins(12, 12, 12, 12)
        reading_layout.setSpacing(0)

        # 2.1 Top bar
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        
        self._toggle_sidebar_btn = QPushButton("☰ 目录")
        self._toggle_sidebar_btn.setIcon(QIcon(_icon_path("sidebar")))
        self._toggle_sidebar_btn.setToolTip("目录面板")
        self._toggle_sidebar_btn.setText("")
        self._toggle_sidebar_btn.setStyleSheet("background: rgba(0,0,0,0.05); color: rgba(0,0,0,0.6); border: none; border-radius: 4px;")
        self._toggle_sidebar_btn.setFixedSize(40, 36)
        self._toggle_sidebar_btn.clicked.connect(self._toggle_sidebar)

        self._back_btn = HoverButton("")
        self._back_btn.setIcon(QIcon(_icon_path("back")))
        self._back_btn.setToolTip("返回书架")
        self._back_btn.setFixedSize(40, 36)
        self._back_btn.clicked.connect(self.backRequested)

        self._header_info = QLabel("未打开书籍")
        self._header_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._header_info.setStyleSheet("color: rgba(0, 0, 0, 0.4); font-size: 13px;")

        self._toggle_settings_btn = QPushButton("")
        self._toggle_settings_btn.setIcon(QIcon(_icon_path("settings")))
        self._toggle_settings_btn.setToolTip("显示设置")
        self._toggle_settings_btn.setStyleSheet("background: rgba(0,0,0,0.05); color: rgba(0,0,0,0.6); border: none; border-radius: 4px;")
        self._toggle_settings_btn.setFixedSize(40, 36)
        self._toggle_settings_btn.clicked.connect(self._toggle_settings)

        top_bar.addWidget(self._back_btn)
        top_bar.addWidget(self._toggle_sidebar_btn)
        top_bar.addWidget(self._header_info, 1)
        top_bar.addWidget(self._toggle_settings_btn)

        # 2.2 Text container
        text_container = QWidget()
        text_layout = QHBoxLayout(text_container)
        text_layout.setContentsMargins(0, 10, 0, 10)
        text_layout.setSpacing(0)
        
        # Side prev button
        self._btn_prev_area = QPushButton("")
        self._btn_prev_area.setIcon(QIcon(_icon_path("chevron-left")))
        self._btn_prev_area.setToolTip("上一章/上一页")
        self._btn_prev_area.setIconSize(QSize(18, 18))
        self._btn_prev_area.setFixedWidth(40)
        self._btn_prev_area.setStyleSheet("background: transparent; border: none;")
        self._btn_prev_area.clicked.connect(self._go_prev)
        
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._text.customContextMenuRequested.connect(self._show_text_context_menu)
        self._text.copyAvailable.connect(self._on_copy_available)
        self._text.verticalScrollBar().setStyleSheet("""
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
            }
            QScrollBar::handle:vertical {
                background: rgba(0, 0, 0, 0.05);
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(0, 0, 0, 0.4);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """)
        self._text.setFrameShape(QFrame.Shape.NoFrame)
        self._text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._text.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)
        
        # Side next button
        self._btn_next_area = QPushButton("")
        self._btn_next_area.setIcon(QIcon(_icon_path("chevron-right")))
        self._btn_next_area.setToolTip("下一章/下一页")
        self._btn_next_area.setIconSize(QSize(18, 18))
        self._btn_next_area.setFixedWidth(40)
        self._btn_next_area.setStyleSheet("background: transparent; border: none;")
        self._btn_next_area.clicked.connect(self._go_next)

        text_layout.addWidget(self._btn_prev_area)
        text_layout.addWidget(self._text, 1)
        text_layout.addWidget(self._btn_next_area)

        # 2.3 Bottom bar
        bottom_bar = QHBoxLayout()
        bottom_bar.setContentsMargins(20, 10, 20, 10)

        self._progress_slider = QSlider(Qt.Orientation.Horizontal)
        self._progress_slider.setRange(0, 1000)
        self._progress_slider.setStyleSheet("QSlider::handle:horizontal { background: rgba(0,0,0,0.3); width: 8px; border-radius: 4px; margin: -5px 0; } QSlider::groove:horizontal { background: rgba(0,0,0,0.1); height: 4px; border-radius: 2px; }")
        self._progress_slider.valueChanged.connect(self._on_slider_changed)

        self._progress_label = QLabel("0%")
        self._progress_label.setStyleSheet("color: rgba(0,0,0,0.5);")

        bottom_bar.addWidget(self._progress_slider, 1)
        bottom_bar.addSpacing(12)
        bottom_bar.addWidget(self._progress_label)

        reading_layout.addLayout(top_bar)
        reading_layout.addWidget(text_container, 1)
        reading_layout.addLayout(bottom_bar)

        # 3. Right Settings Panel
        self._settings_panel = ReaderSettingsPanel(self._visual_settings)
        self._settings_panel.settingsChanged.connect(self._apply_visual_settings)
        self._settings_panel.hide()

        
        self._search_panel = SearchPanel(self)
        self._search_panel.searchRequested.connect(self._perform_search)
        self._search_panel.matchSelected.connect(self._goto_match)
        shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        shortcut.activated.connect(self._toggle_search)
        self._sc_prev = QShortcut(QKeySequence(self._visual_settings.shortcut_prev), self)
        self._sc_prev.activated.connect(self._go_prev)
        self._sc_next = QShortcut(QKeySequence(self._visual_settings.shortcut_next), self)
        self._sc_next.activated.connect(self._go_next)

        self._quick_bar = SelectionQuickBar(self)
        self._quick_bar.bookmarkClicked.connect(self._add_bookmark_from_selection)
        self._quick_bar.highlightClicked.connect(self._add_highlight_from_selection)
        self._quick_bar.noteClicked.connect(self._add_note_from_selection)

        self.main_layout.addWidget(self._sidebar, 0)
        self.main_layout.addWidget(self.reading_area, 1)
        self.main_layout.addWidget(self._settings_panel, 0)

        self._apply_visual_settings(self._visual_settings)

    def _toggle_settings(self) -> None:
        self._settings_panel.setVisible(not self._settings_panel.isVisible())

    def _toggle_sidebar(self) -> None:
        self._sidebar.setVisible(not self._sidebar.isVisible())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_line_wrap_width()

    def load_book(self, book: Book) -> None:
        self._book = book
        self._bookmarks = list(getattr(book, "bookmarks", []))
        self._highlights = list(getattr(book, "highlights", []))
        self._notes = list(getattr(book, "notes", []))
        self._set_header_text()
        self._text.clear()

        if not book.file_path:
            self._chapters = [ChapterItem("全文", "该书籍没有关联本地文件路径。")]
            self._finish_load(book.read_progress)
            return

        path = Path(book.file_path)
        ext = path.suffix.lower()
        if ext == ".txt":
            content = self._read_txt_raw(path)
            self._chapters = parse_txt(content)
        elif ext == ".epub":
            self._chapters = parse_epub(str(path))
        elif ext in {".mobi", ".azw3"}:
            self._chapters = parse_mobi(str(path))
        else:
            self._chapters = [ChapterItem("格式不支持", f"当前不支持 {ext} 格式解析。")]

        self._format_chapters(self._chapters)
        self._finish_load(book.read_progress)

    def _read_txt_raw(self, path: Path) -> str:
        for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk"):
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
            except OSError as exc:
                return f"读取失败: {exc}"
        return "读取失败: 编码不受支持。"

    def _format_chapters(self, chapters: list[ChapterItem]):
        """Format text universally with ideograph indents."""
        for ch in chapters:
            cleaned = []
            for line in ch.text.splitlines():
                s = line.strip()
                if s:
                    cleaned.append("　　" + s)
                else:
                    cleaned.append("")
            ch.text = "\n".join(cleaned)

    def _finish_load(self, saved_progress: float):
        self._sidebar.populate_toc(self._chapters)
        self._sidebar.populate_annotations(self._bookmarks, self._highlights, self._notes)
        self._current_chapter_idx = 0
        self._render_current_mode()
        self._set_progress(saved_progress)
        self._apply_visual_settings(self._visual_settings)

    # ----------------------------------------------------
    # MODE RENDERING & NAVIGATION LOGIC
    # ----------------------------------------------------

    def _render_current_mode(self):
        """Update QTextEdit based on mode vs chapters state."""
        mode = self._visual_settings.reading_mode
        self._btn_prev_area.setVisible(mode != "full_scroll")
        self._btn_next_area.setVisible(mode != "full_scroll")
        
        if mode == "full_scroll":
            # Combine all texts
            full_text = "\n\n\n".join([f"【 {ch.title} 】\n{ch.text}" for ch in self._chapters])
            self._text.setPlainText(full_text)
            self._text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        else:
            # Single chapter or Paginated load just the current chapter
            ch = self._chapters[self._current_chapter_idx]
            self._text.setPlainText(f"【 {ch.title} 】\n\n{ch.text}")
            
            if mode == "paginated":
                self._text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            else: # chapter_scroll
                self._text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def _go_prev(self):
        mode = self._visual_settings.reading_mode
        bar = self._text.verticalScrollBar()
        
        if mode == "paginated":
            if bar.value() <= bar.minimum():
                if self._current_chapter_idx > 0:
                    self._jump_to_chapter(self._current_chapter_idx - 1)
                    # For a real complete app, jump scrollbar to max here, but let's jump to top of prev chapter for simplicity
            else:
                bar.setValue(bar.value() - self._text.viewport().height())
        elif mode == "chapter_scroll":
            if self._current_chapter_idx > 0:
                self._jump_to_chapter(self._current_chapter_idx - 1)
                
    def _go_next(self):
        mode = self._visual_settings.reading_mode
        bar = self._text.verticalScrollBar()
        
        if mode == "paginated":
            if bar.value() >= bar.maximum() - 10: # leeway
                if self._current_chapter_idx < len(self._chapters) - 1:
                    self._jump_to_chapter(self._current_chapter_idx + 1)
            else:
                bar.setValue(bar.value() + self._text.viewport().height())
        elif mode == "chapter_scroll":
            if self._current_chapter_idx < len(self._chapters) - 1:
                self._jump_to_chapter(self._current_chapter_idx + 1)

    def _jump_to_chapter(self, index: int) -> None:
        if index < 0 or index >= len(self._chapters):
            return

        mode = self._visual_settings.reading_mode
        if mode == "full_scroll":
            from PyQt6.QtCore import QTimer
            target_str = "\n\n\n".join([f"【 {ch.title} 】\n{ch.text}" for ch in self._chapters[:index]])
            pos = len(target_str)
            if index > 0: pos += 3
            cursor = self._text.textCursor()
            cursor.setPosition(pos)
            self._text.setTextCursor(cursor)
            self._text.ensureCursorVisible()
            QTimer.singleShot(0, lambda: self._on_scroll_changed(self._text.verticalScrollBar().value()))
        else:
            # Single/Paginated
            self._current_chapter_idx = index
            self._render_current_mode()
            self._text.verticalScrollBar().setValue(0)
            
            # Recalculate generic ratio purely by chapter index
            ratio = index / max(1, len(self._chapters) - 1)
            
            self._syncing = True
            self._progress_slider.setValue(int(ratio * 1000))
            self._progress_label.setText(f"{int(ratio * 100)}%")
            self._syncing = False
            
            self._set_header_text(self._chapters[index].title)
            
            if self._book and self._book.file_path:
                self.progressChanged.emit(self._book.file_path, ratio)

    # ----------------------------------------------------
    # PROGRESS & SYNCS
    # ----------------------------------------------------

    def _on_slider_changed(self, value: int) -> None:
        if self._syncing: return

        ratio = value / 1000
        mode = self._visual_settings.reading_mode
        
        self._syncing = True
        if mode == "full_scroll":
            scrollbar = self._text.verticalScrollBar()
            max_scroll = max(scrollbar.maximum(), 1)
            scrollbar.setValue(int(ratio * max_scroll))
        else:
            # Shift chapters instead of scrolling the small box
            target_idx = int(ratio * (len(self._chapters) - 1))
            self._syncing = False # We override the flow here
            self._jump_to_chapter(target_idx)
            return

        self._syncing = False
        self._update_progress_display(ratio)

    def _on_scroll_changed(self, value: int) -> None:
        if self._syncing: return

        mode = self._visual_settings.reading_mode
        if mode != "full_scroll":
            # For chapter scroll, we don't move the global slider based on local chapter scroll, 
            # or maybe we do tiny fractions. To keep it simple, we leave the slider representing chapter index.
            # Except paginated mode just hides it and drives via Next/Prev.
            return

        scrollbar = self._text.verticalScrollBar()
        max_scroll = max(scrollbar.maximum(), 1)
        ratio = value / max_scroll if max_scroll > 0 else 0

        self._syncing = True
        self._progress_slider.setValue(int(ratio * 1000))
        self._syncing = False

        self._update_progress_display(ratio)

    def _set_progress(self, ratio: float) -> None:
        bounded = min(max(ratio, 0.0), 1.0)
        self._syncing = True
        self._progress_slider.setValue(int(bounded * 1000))
        self._syncing = False
        self._on_slider_changed(int(bounded * 1000))

    def _update_progress_display(self, ratio: float):
        mode = self._visual_settings.reading_mode
        if not self._chapters:
            self._progress_label.setText(f"{int(ratio * 100)}%")
            return

        if mode == "full_scroll":
            idx = int(ratio * (len(self._chapters) - 1))
            ch = self._chapters[idx]
            txt = f"{ch.title} | 全书 {int(ratio * 100)}%"
            self._set_header_text(ch.title)
        else:
            ch = self._chapters[self._current_chapter_idx]
            # Since the progress slider tracks chapters, the percentage is roughly chapters / total.
            txt = f"{ch.title} | {self._current_chapter_idx + 1}/{len(self._chapters)}"
            self._set_header_text(ch.title)

        self._progress_label.setText(txt)
        if self._book and self._book.file_path:
            self.progressChanged.emit(self._book.file_path, ratio)

    # ----------------------------------------------------
    # VISUALS
    # ----------------------------------------------------

    def _set_header_text(self, chapter_title: str = "") -> None:
        if not self._book:
            self._header_info.setText("未打开书籍")
            return
        
        color = QColor(self._visual_settings.text_color)
        self._header_info.setStyleSheet(f"color: {color.name()}; opacity: 0.5; font-size: 13px;")

        if chapter_title:
            self._header_info.setText(f"{self._book.title} - {chapter_title}")
        else:
            self._header_info.setText(self._book.title)

    def _apply_visual_settings(self, settings: ReaderVisualSettings) -> None:
        old_mode = self._visual_settings.reading_mode
        self._visual_settings = settings
        
        if old_mode != settings.reading_mode:
            self._render_current_mode() # Repaint content if mode shifted!

        # Preserve progress roughly 
        ratio = self._progress_slider.value() / 1000.0

        self.reading_area.setStyleSheet(f"QWidget {{ background: {settings.background_color}; color: {settings.text_color}; }}")

        font = QFont(settings.font_family_en, settings.font_size)
        try:
            font.setFamilies([settings.font_family_en, settings.font_family_zh])
        except AttributeError:
            pass # PyQt6 sometimes does not expose setFamilies directly on font easily
        self._text.setFont(font)

        if hasattr(self, '_sc_prev'):
            self._sc_prev.setKey(QKeySequence(settings.shortcut_prev))
        if hasattr(self, '_sc_next'):
            self._sc_next.setKey(QKeySequence(settings.shortcut_next))
        
        doc = self._text.document()
        if doc and doc.characterCount() > 0:
            cursor = QTextCursor(doc)
            cursor.select(QTextCursor.SelectionType.Document)
            block_format = cursor.blockFormat()
            block_format.setLineHeight(settings.line_spacing_percent, 1) 
            block_format.setBottomMargin(settings.font_size * 0.8) 
            cursor.mergeBlockFormat(block_format)

        self._text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._update_line_wrap_width()

        self._set_progress(ratio)

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

    def _on_copy_available(self, available: bool) -> None:
        if not available:
            self._quick_bar.hide()
            return

        cursor = self._text.textCursor()
        if not cursor.hasSelection():
            self._quick_bar.hide()
            return

        start_cursor = QTextCursor(self._text.document())
        start_cursor.setPosition(cursor.selectionStart())
        rect = self._text.cursorRect(start_cursor)
        local_top = self._text.mapTo(self, rect.topLeft())
        x = max(8, min(local_top.x(), self.width() - self._quick_bar.width() - 8))
        y = max(8, local_top.y() - self._quick_bar.sizeHint().height() - 8)
        self._quick_bar.move(x, y)
        self._quick_bar.resize(self._quick_bar.sizeHint())
        self._quick_bar.show()
        self._quick_bar.raise_()

    def _show_text_context_menu(self, pos: QPoint) -> None:
        menu = self._text.createStandardContextMenu()
        cursor = self._text.textCursor()
        if cursor.hasSelection():
            menu.addSeparator()

            act_bookmark = QAction(QIcon(_icon_path("bookmark")), "添加书签", self)
            act_bookmark.triggered.connect(self._add_bookmark_from_selection)
            menu.addAction(act_bookmark)

            act_highlight = QAction(QIcon(_icon_path("highlight")), "添加标记", self)
            act_highlight.triggered.connect(self._add_highlight_from_selection)
            menu.addAction(act_highlight)

            act_note = QAction(QIcon(_icon_path("note")), "添加笔记", self)
            act_note.triggered.connect(self._add_note_from_selection)
            menu.addAction(act_note)

        menu.exec(self._text.mapToGlobal(pos))

    def _selection_record(self) -> dict | None:
        cursor = self._text.textCursor()
        if not cursor.hasSelection() or not self._chapters:
            return None

        selected = cursor.selectedText().replace("\u2029", "\n").strip()
        if not selected:
            return None

        chapter_idx = self._current_chapter_idx
        chapter_title = self._chapters[chapter_idx].title
        mode = self._visual_settings.reading_mode
        if mode == "full_scroll":
            sel_pos = cursor.selectionStart()
            ranges: list[tuple[int, int]] = []
            offset = 0
            for i, ch in enumerate(self._chapters):
                head_len = len(f"【 {ch.title} 】\n")
                start = offset + head_len
                end = start + len(ch.text)
                ranges.append((start, end))
                offset = end + (3 if i < len(self._chapters) - 1 else 0)
            for i, (start, end) in enumerate(ranges):
                if start <= sel_pos <= end:
                    chapter_idx = i
                    chapter_title = self._chapters[i].title
                    local_start = max(0, sel_pos - start)
                    break
            else:
                local_start = 0
        else:
            head_len = len(f"【 {chapter_title} 】\n\n")
            local_start = max(0, cursor.selectionStart() - head_len)

        return {
            "chapter_index": chapter_idx,
            "chapter_title": chapter_title,
            "local_start": local_start,
            "preview": selected[:80],
            "selected_text": selected,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }

    def _add_bookmark_from_selection(self) -> None:
        rec = self._selection_record()
        if rec is None:
            return
        self._bookmarks.append(rec)
        self._after_annotation_changed()

    def _add_highlight_from_selection(self) -> None:
        rec = self._selection_record()
        if rec is None:
            return
        self._highlights.append(rec)
        self._after_annotation_changed()

    def _add_note_from_selection(self) -> None:
        rec = self._selection_record()
        if rec is None:
            return
        text, ok = QInputDialog.getMultiLineText(self, "添加笔记", "笔记内容:")
        if not ok:
            return
        rec["note"] = text.strip()
        self._notes.append(rec)
        self._after_annotation_changed()

    def _after_annotation_changed(self) -> None:
        self._quick_bar.hide()
        self._sidebar.populate_annotations(self._bookmarks, self._highlights, self._notes)
        if self._book and self._book.file_path:
            self.annotationsChanged.emit(self._book.file_path, self._bookmarks, self._highlights, self._notes)

    def _jump_to_annotation(self, kind: str, idx: int) -> None:
        source = {
            "bookmark": self._bookmarks,
            "highlight": self._highlights,
            "note": self._notes,
        }.get(kind, [])
        if idx < 0 or idx >= len(source):
            return

        rec = source[idx]
        chapter_idx = int(rec.get("chapter_index", 0))
        chapter_idx = max(0, min(chapter_idx, len(self._chapters) - 1))
        self._jump_to_chapter(chapter_idx)

        selected_text = rec.get("selected_text", "")
        if not selected_text:
            return

        plain = self._text.toPlainText()
        pos = plain.find(selected_text)
        if pos < 0:
            return
        cursor = self._text.textCursor()
        cursor.setPosition(pos)
        cursor.setPosition(pos + len(selected_text), QTextCursor.MoveMode.KeepAnchor)
        self._text.setTextCursor(cursor)
        self._text.ensureCursorVisible()


    def _toggle_search(self) -> None:
        if self._search_panel.isVisible():
            self._search_panel.hide()
            self._text.setExtraSelections([])
        else:
            self._search_panel.show()
            self._search_panel.raise_()
            self._reposition_search_panel()
            self._search_panel.input.setFocus()
            self._search_panel.input.selectAll()

    def _reposition_search_panel(self) -> None:
        if not hasattr(self, '_search_panel'): return
        w = self.width()
        self._search_panel.setGeometry(w - 340 - 280, 50, 320, 500)

    def _perform_search(self, term: str) -> None:
        if not term: return
        doc = self._text.document()
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#ffda6a"))
        fmt.setForeground(QColor("#000000"))
        
        matches = []
        extras = []
        
        plain_text = self._text.toPlainText()
        escaped_term = html.escape(term)
        
        for found in re.finditer(re.escape(term), plain_text, flags=re.IGNORECASE):
            start = found.start()
            end = found.end()
            ctx_start = max(0, start - 20)
            ctx_end = min(len(plain_text), end + 20)
            
            context_raw = ("..." if ctx_start > 0 else "") + plain_text[ctx_start:ctx_end].replace("\n", " ") + ("..." if ctx_end < len(plain_text) else "")
            
            context_html = html.escape(context_raw)
            pattern = re.compile(f"({re.escape(escaped_term)})", flags=re.IGNORECASE)
            context_html = pattern.sub(r'<span style="background-color: #ffda6a; color: #000; font-weight: bold;">\1</span>', context_html)
            
            matches.append((start, end, context_html))
            
            cursor = QTextCursor(doc)
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            extra = QTextEdit.ExtraSelection()
            extra.cursor = cursor
            extra.format = fmt
            extras.append(extra)
            
            if len(matches) > 100: break
            
        self._text.setExtraSelections(extras)
        self._search_panel.set_results(matches)

    def _goto_match(self, start: int, end: int) -> None:
        cursor = self._text.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self._text.setTextCursor(cursor)
        self._text.ensureCursorVisible()
