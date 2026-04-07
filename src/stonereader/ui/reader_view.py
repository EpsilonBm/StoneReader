"""Reader view supporting multiple modes and full features."""

from __future__ import annotations

import bisect
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
import html
import json
import base64
from typing import Callable

from PyQt6.QtCore import QPoint, Qt, pyqtSignal, QSize, QEvent, QTimer, QPropertyAnimation, QEasingCurve, QRect, QUrl, QRegularExpression
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor, QFont, QKeySequence, QShortcut, QIcon, QAction, QPainter, QPixmap, QTextImageFormat, QImage, QTextDocument
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFontComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QKeySequenceEdit,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QStyleOptionSlider,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QToolTip,
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
    middle_scroll_speed_cap: int = 36
    middle_scroll_gain_percent: int = 12


class HoverButton(QPushButton):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setMouseTracking(True)
        self.setStyleSheet("background: transparent; color: inherit; border: none; border-radius: 4px;")

    def enterEvent(self, event):
        self.setStyleSheet("background: rgba(0, 0, 0, 0.08); color: inherit; border-radius: 4px; font-weight: bold;")
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet("background: transparent; color: inherit; border: none; border-radius: 4px;")
        super().leaveEvent(event)


def _icon_path(name: str) -> str:
    root = Path(__file__).resolve().parents[3]
    return str(root / "source" / "icon" / f"{name}.svg")


class SelectionQuickBar(QFrame):
    bookmarkClicked = pyqtSignal()
    highlightColorClicked = pyqtSignal(str)
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
        row.setSpacing(6)

        self._btn_bm = QToolButton(self)
        self._btn_bm.setIcon(QIcon(_icon_path("bookmark")))
        self._btn_bm.setToolTip("添加书签")
        self._btn_bm.setIconSize(QSize(18, 18))
        self._btn_bm.clicked.connect(self.bookmarkClicked)

        self._hl_colors = ["#ffef88", "#ffd1dc", "#c9f7d7", "#cfe3ff"]
        self._hl_color_btns: list[QToolButton] = []
        for color in self._hl_colors:
            btn = QToolButton(self)
            btn.setToolTip(f"标记颜色 {color}")
            btn.setFixedSize(16, 16)
            btn.setStyleSheet(
                f"QToolButton {{ border: 1px solid #94a3b8; border-radius: 8px; background: {color}; padding: 0px; }}"
                "QToolButton:hover { border-color: #334155; }"
            )
            btn.clicked.connect(lambda _=False, c=color: self.highlightColorClicked.emit(c))
            self._hl_color_btns.append(btn)

        self._btn_note = QToolButton(self)
        self._btn_note.setIcon(QIcon(_icon_path("note")))
        self._btn_note.setToolTip("添加笔记")
        self._btn_note.setIconSize(QSize(18, 18))
        self._btn_note.clicked.connect(self.noteClicked)

        for btn in (self._btn_bm, self._btn_note):
            btn.setStyleSheet(
                "QToolButton { border: none; padding: 4px; border-radius: 6px; }"
                "QToolButton:hover { background: #e2e8f0; }"
            )
        row.addWidget(self._btn_bm)
        for btn in self._hl_color_btns:
            row.addWidget(btn)
        row.addWidget(self._btn_note)

        self.hide()


class ChapterProgressSlider(QSlider):
    def __init__(self, orientation: Qt.Orientation, parent: QWidget | None = None) -> None:
        super().__init__(orientation, parent)
        self._markers: list[tuple[float, str]] = []
        self.setMouseTracking(True)

    def set_markers(self, markers: list[tuple[float, str]]) -> None:
        self._markers = [(m, t) for m, t in markers if 0.0 < m < 1.0]
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._markers:
            return

        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderGroove,
            self,
        )
        if groove.width() <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(60, 64, 67, 140))

        y = groove.center().y()
        for ratio, _ in self._markers:
            x = groove.left() + int(ratio * groove.width())
            painter.drawEllipse(QPoint(x, y), 2, 2)

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        title = self._marker_title_at(event.position().x())
        if title:
            QToolTip.showText(event.globalPosition().toPoint(), title, self)
        else:
            QToolTip.hideText()

    def leaveEvent(self, event) -> None:
        QToolTip.hideText()
        super().leaveEvent(event)

    def _marker_title_at(self, x: float) -> str | None:
        if not self._markers:
            return None
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderGroove,
            self,
        )
        if groove.width() <= 0:
            return None
        nearest_title = None
        nearest_dist = 9999.0
        for ratio, title in self._markers:
            marker_x = groove.left() + ratio * groove.width()
            dist = abs(marker_x - x)
            if dist < nearest_dist:
                nearest_dist = dist
                nearest_title = title
        if nearest_dist <= 6.0:
            return nearest_title
        return None


class InlineNoteEditor(QFrame):
    submitRequested = pyqtSignal(str)
    canceled = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("InlineNoteEditor")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(
            "QFrame#InlineNoteEditor { background: rgba(255,255,255,0.98); border: 1px solid #cbd5e1; border-radius: 10px; }"
            "QTextEdit { border: 1px solid #a8b5c9; border-radius: 6px; padding: 6px; background: #fffef7; color: #111827; }"
            "QPushButton { border: none; border-radius: 6px; padding: 6px 10px; background: transparent; color: #0f172a; }"
            "QPushButton:hover { background: #e2e8f0; }"
            "QToolButton { border: none; border-radius: 6px; padding: 4px; background: transparent; color: #334155; }"
            "QToolButton:hover { background: #e2e8f0; color: #0f172a; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        title = QLabel("添加笔记")
        title.setStyleSheet("font-weight: bold; color: #1f2937;")
        self._close = QToolButton(self)
        self._close.setText("✕")
        self._close.setToolTip("关闭")
        self._close.setFixedSize(22, 22)
        self._close.clicked.connect(self._on_cancel)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self._close)
        self._edit = QTextEdit(self)
        self._edit.setPlaceholderText("输入笔记内容...")
        self._edit.setMinimumHeight(88)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self._cancel = QPushButton("取消", self)
        self._save = QPushButton("保存", self)
        self._cancel.clicked.connect(self._on_cancel)
        self._save.clicked.connect(self._on_submit)
        actions.addWidget(self._cancel)
        actions.addWidget(self._save)

        layout.addLayout(head)
        layout.addWidget(self._edit)
        layout.addLayout(actions)
        self.hide()

    def open_at(self, pos: QPoint) -> None:
        self.move(pos)
        self.resize(280, 170)
        self.show()
        self.raise_()
        self._edit.setFocus()

    def clear_text(self) -> None:
        self._edit.clear()

    def _on_submit(self) -> None:
        self.submitRequested.emit(self._edit.toPlainText().strip())

    def _on_cancel(self) -> None:
        self.hide()
        self.canceled.emit()


class NotePreviewPopup(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("NotePreviewPopup")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(
            "QFrame#NotePreviewPopup { background: #fefdf8; border: 1px solid #d4c593; border-radius: 10px; }"
            "QLabel#NoteTitle { color: #5a460f; font-weight: bold; }"
            "QLabel#NoteBody { color: #1f2937; background: #fff8de; border: 1px solid #e6d7a8; border-radius: 8px; padding: 8px; }"
            "QToolButton { border: none; border-radius: 6px; padding: 4px; color: #6b7280; background: transparent; }"
            "QToolButton:hover { color: #111827; background: #f1f5f9; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        self._title = QLabel("笔记")
        self._title.setObjectName("NoteTitle")
        self._close = QToolButton(self)
        self._close.setText("✕")
        self._close.setToolTip("关闭")
        self._close.setFixedSize(22, 22)
        self._close.clicked.connect(self.hide)
        head.addWidget(self._title)
        head.addStretch(1)
        head.addWidget(self._close)
        self._body = QLabel("")
        self._body.setObjectName("NoteBody")
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addLayout(head)
        layout.addWidget(self._body)
        self.hide()

    def show_note(self, global_pos: QPoint, text: str) -> None:
        self._body.setText(text or "(空笔记)")
        self.resize(320, 180)
        parent = self.parentWidget()
        if parent is None:
            return
        local = parent.mapFromGlobal(global_pos)
        x = min(max(8, local.x() + 10), max(8, parent.width() - self.width() - 8))
        y = min(max(8, local.y() + 10), max(8, parent.height() - self.height() - 8))
        self.move(x, y)
        self.show()
        self.raise_()


class FootnotePopup(QFrame):
    jumpRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FootnotePopup")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(
            "QFrame#FootnotePopup { background: #fbfdff; border: 1px solid #b7c8de; border-radius: 10px; }"
            "QLabel#FootnoteTitle { color: #1e3a5f; font-weight: bold; }"
            "QLabel#FootnoteBody { color: #0f172a; background: #f8fbff; border: 1px solid #d7e3f1; border-radius: 8px; padding: 8px; }"
            "QPushButton { border: none; border-radius: 6px; padding: 6px 10px; background: #e5eefb; color: #0f172a; }"
            "QPushButton:hover { background: #d8e7fb; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._title = QLabel("注释")
        self._title.setObjectName("FootnoteTitle")
        self._body = QLabel("")
        self._body.setObjectName("FootnoteBody")
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self._jump = QPushButton("跳转到注释位置")
        self._close = QPushButton("关闭")
        self._jump.clicked.connect(self.jumpRequested)
        self._close.clicked.connect(self.hide)
        actions.addWidget(self._jump)
        actions.addWidget(self._close)

        layout.addWidget(self._title)
        layout.addWidget(self._body)
        layout.addLayout(actions)
        self.hide()

    def show_footnote(self, global_pos: QPoint, token: str, text: str, can_jump: bool) -> None:
        self._title.setText(f"注释 {token}")
        self._body.setText(text or "(空注释)")
        self._jump.setEnabled(can_jump)
        self.resize(360, 210)
        parent = self.parentWidget()
        if parent is None:
            return
        local = parent.mapFromGlobal(global_pos)
        x = min(max(8, local.x() + 10), max(8, parent.width() - self.width() - 8))
        y = min(max(8, local.y() + 10), max(8, parent.height() - self.height() - 8))
        self.move(x, y)
        self.show()
        self.raise_()


class MediaPreviewPopup(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MediaPreviewPopup")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(
            "QFrame#MediaPreviewPopup { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 10px; }"
            "QLabel#MediaTitle { color: #1f2937; font-weight: bold; }"
            "QLabel#MediaImage { background: #f8fafc; border: 1px solid #dbe3ef; border-radius: 8px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self._title = QLabel("插图")
        self._title.setObjectName("MediaTitle")
        self._image = QLabel("(暂无图片)")
        self._image.setObjectName("MediaImage")
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.setMinimumSize(280, 160)
        self._close = QPushButton("关闭")
        self._close.clicked.connect(self.hide)
        layout.addWidget(self._title)
        layout.addWidget(self._image)
        layout.addWidget(self._close)
        self.hide()

    def show_media(self, global_pos: QPoint, token: str, alt: str, data_url: str) -> None:
        self._title.setText(f"插图 {token}" if token else "插图")
        pix = QPixmap()
        ok = False
        if data_url.startswith("data:") and ";base64," in data_url:
            payload = data_url.split(";base64,", 1)[1]
            try:
                raw = base64.b64decode(payload)
                ok = pix.loadFromData(raw)
            except Exception:
                ok = False
        if ok:
            self._image.setPixmap(pix.scaled(520, 360, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            self._image.setText("")
        else:
            self._image.setPixmap(QPixmap())
            self._image.setText(alt or "(该插图无可用图像数据)")

        self.resize(560, 430)
        parent = self.parentWidget()
        if parent is None:
            return
        local = parent.mapFromGlobal(global_pos)
        x = min(max(8, local.x() + 10), max(8, parent.width() - self.width() - 8))
        y = min(max(8, local.y() + 10), max(8, parent.height() - self.height() - 8))
        self.move(x, y)
        self.show()
        self.raise_()


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
            middle_scroll_speed_cap=settings.middle_scroll_speed_cap,
            middle_scroll_gain_percent=settings.middle_scroll_gain_percent,
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)

        title = QLabel("显示设置")
        title.setStyleSheet("font-weight: bold; font-size: 16px;")
        root.addWidget(title)
        
        self._reading_mode = QComboBox()
        self._reading_mode.addItems(["全书滑动", "单章滑动", "翻页模式（暂不可用）"])
        try:
            item = self._reading_mode.model().item(2)
            if item is not None:
                item.setEnabled(False)
        except Exception:
            pass
        if settings.reading_mode == "full_scroll":
            self._reading_mode.setCurrentIndex(0)
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
        self._font_size_slider = QSlider(Qt.Orientation.Horizontal)
        self._font_size_slider.setRange(12, 40)
        self._font_size_slider.setValue(settings.font_size)
        self._font_size_slider.valueChanged.connect(self._font_size.setValue)
        self._font_size.valueChanged.connect(self._font_size_slider.setValue)

        self._line_spacing = QSpinBox()
        self._line_spacing.setRange(110, 260)
        self._line_spacing.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.PlusMinus)
        self._line_spacing.setMinimumHeight(32)
        self._line_spacing.setSingleStep(10)
        self._line_spacing.setSuffix("%")
        self._line_spacing.setValue(settings.line_spacing_percent)
        self._line_spacing.valueChanged.connect(self._on_changed)
        self._line_spacing_slider = QSlider(Qt.Orientation.Horizontal)
        self._line_spacing_slider.setRange(110, 260)
        self._line_spacing_slider.setSingleStep(10)
        self._line_spacing_slider.setPageStep(10)
        self._line_spacing_slider.setValue(settings.line_spacing_percent)
        self._line_spacing_slider.valueChanged.connect(self._line_spacing.setValue)
        self._line_spacing.valueChanged.connect(self._line_spacing_slider.setValue)

        self._line_width = QSpinBox()
        self._line_width.setRange(50, 100)
        self._line_width.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.PlusMinus)
        self._line_width.setMinimumHeight(32)
        self._line_width.setSuffix("%")
        self._line_width.setValue(settings.line_width_percent)
        self._line_width.valueChanged.connect(self._on_changed)
        self._line_width_slider = QSlider(Qt.Orientation.Horizontal)
        self._line_width_slider.setRange(50, 100)
        self._line_width_slider.setValue(settings.line_width_percent)
        self._line_width_slider.valueChanged.connect(self._line_width.setValue)
        self._line_width.valueChanged.connect(self._line_width_slider.setValue)

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

        self._middle_speed_cap = QSpinBox()
        self._middle_speed_cap.setRange(8, 180)
        self._middle_speed_cap.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.PlusMinus)
        self._middle_speed_cap.setMinimumHeight(32)
        self._middle_speed_cap.setSuffix(" px/帧")
        self._middle_speed_cap.setValue(settings.middle_scroll_speed_cap)
        self._middle_speed_cap.valueChanged.connect(self._on_changed)

        self._middle_speed_gain = QSpinBox()
        self._middle_speed_gain.setRange(2, 80)
        self._middle_speed_gain.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.PlusMinus)
        self._middle_speed_gain.setMinimumHeight(32)
        self._middle_speed_gain.setSuffix(" %")
        self._middle_speed_gain.setValue(settings.middle_scroll_gain_percent)
        self._middle_speed_gain.valueChanged.connect(self._on_changed)
        
        root.addLayout(self._row("阅读模式", self._reading_mode))
        root.addLayout(self._row("英文字体", self._font_family_en))
        root.addLayout(self._row("中文字体", self._font_family_zh))
        root.addLayout(self._row_with_slider("字体大小", self._font_size_slider, self._font_size))
        root.addLayout(self._row_with_slider("行距比例", self._line_spacing_slider, self._line_spacing))
        root.addLayout(self._row_with_slider("居中部分", self._line_width_slider, self._line_width))
        root.addLayout(self._row("文字颜色", self._text_color_btn))
        root.addLayout(self._row("背景颜色", self._bg_color_btn))
        root.addLayout(self._row("上章快捷键", self._shortcut_prev))
        root.addLayout(self._row("下章快捷键", self._shortcut_next))
        root.addLayout(self._row("中键滚动系数", self._middle_speed_gain))
        root.addLayout(self._row("中键滚动上限", self._middle_speed_cap))
        root.addStretch(1)

        self.setStyleSheet("""
            QWidget#SettingsPanel { border-left: 1px solid rgba(0,0,0,0.1); background: #ffffff; color: #1a2333; }
            QSpinBox, QComboBox, QFontComboBox, QKeySequenceEdit { background: #f2f4f7; color: #1a2333; border: 1px solid #c9d0d8; padding: 4px 8px; border-radius: 4px; }
            QSlider::groove:horizontal { background: #d7e0ea; height: 4px; border-radius: 2px; }
            QSlider::handle:horizontal { background: #6b8fb3; width: 12px; margin: -5px 0; border-radius: 6px; }
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

    @staticmethod
    def _row_with_slider(label: str, slider: QSlider, spin: QSpinBox) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        row.addWidget(slider, 1)
        row.addWidget(spin)
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
        self._settings.middle_scroll_speed_cap = self._middle_speed_cap.value()
        self._settings.middle_scroll_gain_percent = self._middle_speed_gain.value()
        
        mode_idx = self._reading_mode.currentIndex()
        if mode_idx == 0:
            self._settings.reading_mode = "full_scroll"
        else:
            self._settings.reading_mode = "chapter_scroll"

        # Emit a fresh value object so ReaderView can reliably compare old/new mode.
        self.settingsChanged.emit(
            ReaderVisualSettings(
                font_family_zh=self._settings.font_family_zh,
                font_family_en=self._settings.font_family_en,
                font_size=self._settings.font_size,
                line_spacing_percent=self._settings.line_spacing_percent,
                line_width_percent=self._settings.line_width_percent,
                text_color=self._settings.text_color,
                background_color=self._settings.background_color,
                reading_mode=self._settings.reading_mode,
                shortcut_prev=self._settings.shortcut_prev,
                shortcut_next=self._settings.shortcut_next,
                middle_scroll_speed_cap=self._settings.middle_scroll_speed_cap,
                middle_scroll_gain_percent=self._settings.middle_scroll_gain_percent,
            )
        )


class ReaderSidebar(QWidget):
    """Left sidebar for TOC, bookmarks, highlights and notes."""
    chapterSelected = pyqtSignal(int)
    annotationSelected = pyqtSignal(str, int)
    annotationDeleteRequested = pyqtSignal(str, int)
    exportRequested = pyqtSignal()
    
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
        self._toc_tree = QTreeWidget()
        self._toc_tree.setHeaderHidden(True)
        self._toc_tree.itemClicked.connect(self._on_toc_clicked)

        self._bm_list = QListWidget()
        self._bm_list.itemClicked.connect(lambda item: self._emit_annotation("bookmark", item))
        self._bm_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._bm_list.customContextMenuRequested.connect(lambda pos: self._delete_from_context("bookmark", self._bm_list, pos))

        self._hl_list = QListWidget()
        self._hl_list.itemClicked.connect(lambda item: self._emit_annotation("highlight", item))
        self._hl_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._hl_list.customContextMenuRequested.connect(lambda pos: self._delete_from_context("highlight", self._hl_list, pos))
        self._hl_filter_bar = QHBoxLayout()
        self._hl_filter_bar.setContentsMargins(0, 0, 0, 0)
        self._hl_filter_bar.setSpacing(6)
        self._hl_records: list[dict] = []
        self._hl_filter_value: str = ""
        self._hl_filter_btns: list[QToolButton] = []

        self._hl_panel = QWidget()
        hl_layout = QVBoxLayout(self._hl_panel)
        hl_layout.setContentsMargins(0, 0, 0, 0)
        hl_layout.setSpacing(4)
        hl_layout.addLayout(self._hl_filter_bar)
        hl_layout.addWidget(self._hl_list, 1)

        self._note_list = QListWidget()
        self._note_list.itemClicked.connect(lambda item: self._emit_annotation("note", item))
        self._note_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._note_list.customContextMenuRequested.connect(lambda pos: self._delete_from_context("note", self._note_list, pos))

        self._stack.addWidget(self._toc_tree)
        self._stack.addWidget(self._bm_list)
        self._stack.addWidget(self._hl_panel)
        self._stack.addWidget(self._note_list)
        
        layout.addLayout(tabs_layout)
        self._btn_export = QPushButton("导出注释")
        self._btn_export.setStyleSheet(
            "QPushButton { border: none; background: transparent; border-radius: 6px; padding: 6px 8px; color: #334155; }"
            "QPushButton:hover { background: #e2e8f0; color: #0f172a; }"
        )
        self._btn_export.clicked.connect(self.exportRequested)
        layout.addWidget(self._btn_export)
        layout.addWidget(self._stack)
        self._btn_toc.setChecked(True)

        self.setStyleSheet(
            "QWidget#ReaderSidebar { border-right: 1px solid rgba(0,0,0,0.1); background: #ffffff; color: #1a2333; }"
            "QListWidget { border: none; background: transparent; padding: 4px; }"
            "QListWidget::item { padding: 6px 8px; border-radius: 6px; background: transparent; }"
            "QListWidget::item:hover { background: #eef2f7; }"
            "QListWidget::item:selected { background: #e2e8f0; }"
            "QToolButton { border: none; padding: 6px; border-radius: 6px; background: transparent; }"
            "QToolButton:checked, QToolButton:hover { background: #e2e8f0; }"
        )

    def _switch_panel(self, index: int) -> None:
        self._stack.setCurrentIndex(index)

    def populate_toc(self, chapters: list[ChapterItem]):
        self._toc_tree.clear()
        parent_map: dict[str, QTreeWidgetItem] = {}
        part_title_re = re.compile(r"^(第[一二三四五六七八九十百千万0-9]+[部卷])$")
        nested_re = re.compile(r"^(第[一二三四五六七八九十百千万0-9]+[部卷])\s+(.+)$")

        for idx, ch in enumerate(chapters):
            title = (ch.title or "").strip() or f"章节 {idx+1}"
            m = nested_re.match(title)
            if m:
                parent_title = m.group(1)
                child_title = m.group(2).strip() or title
                parent_item = parent_map.get(parent_title)
                if parent_item is None:
                    parent_item = QTreeWidgetItem([parent_title])
                    parent_item.setData(0, Qt.ItemDataRole.UserRole, None)
                    self._toc_tree.addTopLevelItem(parent_item)
                    parent_map[parent_title] = parent_item
                child_item = QTreeWidgetItem([child_title])
                child_item.setData(0, Qt.ItemDataRole.UserRole, idx)
                parent_item.addChild(child_item)
                continue

            if part_title_re.match(title):
                parent_item = parent_map.get(title)
                if parent_item is None:
                    parent_item = QTreeWidgetItem([title])
                    self._toc_tree.addTopLevelItem(parent_item)
                    parent_map[title] = parent_item
                parent_item.setData(0, Qt.ItemDataRole.UserRole, idx)
                continue

            item = QTreeWidgetItem([title])
            item.setData(0, Qt.ItemDataRole.UserRole, idx)
            self._toc_tree.addTopLevelItem(item)

        self._toc_tree.expandToDepth(0)
            
    def _on_toc_clicked(self, item, _column: int = 0):
        idx = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(idx, int):
            self.chapterSelected.emit(idx)

    def populate_annotations(self, bookmarks: list[dict], highlights: list[dict], notes: list[dict]) -> None:
        self._fill_annotation_list(self._bm_list, bookmarks, "bookmark")
        self._hl_records = list(highlights)
        self._sync_highlight_filter_options()
        self._refresh_highlight_list()
        self._fill_annotation_list(self._note_list, notes, "note")

    def _sync_highlight_filter_options(self) -> None:
        while self._hl_filter_bar.count() > 0:
            item = self._hl_filter_bar.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._hl_filter_btns.clear()
        colors = sorted({str(rec.get("color", "#ffef88")) for rec in self._hl_records})

        all_btn = QToolButton(self)
        all_btn.setToolTip("所有标记")
        all_btn.setCheckable(True)
        all_btn.setChecked(self._hl_filter_value == "")
        all_btn.setFixedSize(16, 16)
        all_btn.setStyleSheet(
            "QToolButton { border: 1px solid #64748b; border-radius: 8px;"
            "background: qconicalgradient(cx:0.5, cy:0.5, angle:0, stop:0 #ffef88, stop:0.25 #ffd1dc, stop:0.5 #c9f7d7, stop:0.75 #cfe3ff, stop:1 #ffef88); }"
            "QToolButton:checked { border: 2px solid #334155; }"
        )
        all_btn.clicked.connect(lambda _=False: self._set_highlight_filter(""))
        self._hl_filter_bar.addWidget(all_btn)
        self._hl_filter_btns.append(all_btn)

        for color in colors:
            btn = QToolButton(self)
            btn.setToolTip(color)
            btn.setCheckable(True)
            btn.setChecked(self._hl_filter_value == color)
            btn.setFixedSize(16, 16)
            btn.setStyleSheet(
                f"QToolButton {{ border: 1px solid #64748b; border-radius: 8px; background: {color}; }}"
                "QToolButton:checked { border: 2px solid #334155; }"
            )
            btn.clicked.connect(lambda _=False, c=color: self._set_highlight_filter(c))
            self._hl_filter_bar.addWidget(btn)
            self._hl_filter_btns.append(btn)
        self._hl_filter_bar.addStretch(1)

    def _set_highlight_filter(self, color: str) -> None:
        self._hl_filter_value = color
        self._sync_highlight_filter_options()
        self._refresh_highlight_list()

    def _refresh_highlight_list(self) -> None:
        selected_color = self._hl_filter_value

        while self._hl_list.count() > 0:
            item = self._hl_list.takeItem(0)
            widget = self._hl_list.itemWidget(item)
            if widget is not None:
                self._hl_list.removeItemWidget(item)
                widget.deleteLater()
            del item
        self._hl_list.clear()

        for idx, rec in enumerate(self._hl_records):
            color = str(rec.get("color", "#ffef88"))
            if selected_color and color != selected_color:
                continue
            preview = rec.get("preview", "")
            chapter = rec.get("chapter_title", "")
            head = f"{chapter} | {preview}" if chapter else preview
            item = QListWidgetItem(f"● {head[:120]}")
            item.setToolTip(head)
            item.setData(Qt.ItemDataRole.UserRole, idx)
            item.setForeground(QColor(color))
            self._hl_list.addItem(item)

    def _fill_annotation_list(self, list_widget: QListWidget, records: list[dict], kind: str) -> None:
        # QListWidget with setItemWidget may keep stale widgets if not explicitly detached.
        while list_widget.count() > 0:
            item = list_widget.takeItem(0)
            widget = list_widget.itemWidget(item)
            if widget is not None:
                list_widget.removeItemWidget(item)
                widget.deleteLater()
            del item
        list_widget.clear()
        for idx, rec in enumerate(records):
            preview = rec.get("preview", "")
            chapter = rec.get("chapter_title", "")
            note_text = rec.get("note", "") if kind == "note" else ""
            head = f"{chapter} | {preview}" if chapter else preview
            text = f"{head}\n{note_text}" if note_text else head
            item = QListWidgetItem("" if kind == "note" else text[:120])
            item.setToolTip(text)
            item.setData(Qt.ItemDataRole.UserRole, idx)
            list_widget.addItem(item)
            if kind == "note":
                row = QWidget(list_widget)
                lay = QVBoxLayout(row)
                lay.setContentsMargins(4, 4, 4, 4)
                lay.setSpacing(2)
                head_label = QLabel(head)
                head_label.setStyleSheet("font-weight: bold; color: #1f2937;")
                head_label.setWordWrap(True)
                note_label = QLabel(note_text)
                note_label.setStyleSheet("color: #334155;")
                note_label.setWordWrap(True)
                lay.addWidget(head_label)
                lay.addWidget(note_label)
                item.setSizeHint(row.sizeHint())
                list_widget.setItemWidget(item, row)

    def _emit_annotation(self, kind: str, item: QListWidgetItem) -> None:
        idx = item.data(Qt.ItemDataRole.UserRole)
        self.annotationSelected.emit(kind, idx)

    def _delete_from_context(self, kind: str, list_widget: QListWidget, pos: QPoint) -> None:
        item = list_widget.itemAt(pos)
        if item is None:
            return
        idx = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(list_widget)
        delete_action = menu.addAction("删除")
        chosen = menu.exec(list_widget.mapToGlobal(pos))
        if chosen is delete_action:
            self.annotationDeleteRequested.emit(kind, idx)

class SearchPanel(QWidget):
    searchRequested = pyqtSignal(str)
    matchSelected = pyqtSignal(int, int)
    prevRequested = pyqtSignal()
    nextRequested = pyqtSignal()
    closeRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SearchPanel")
        self.setMinimumWidth(320)
        self.setMinimumHeight(400)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        box = QFrame(self)
        box.setStyleSheet("background: #f5f7fb; border: 1px solid #d5dbe6; border-radius: 8px;")
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(8, 8, 8, 8)
        box_layout.setSpacing(6)

        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("搜索当前视图...")
        self.input.setStyleSheet(
            "QLineEdit { background: #ffffff; color: #0f172a; border: 1px solid #94a3b8; border-radius: 6px; padding: 4px 8px; }"
            "QLineEdit:focus { border-color: #3b82f6; }"
        )
        self.input.returnPressed.connect(self._do_search)
        self._btn = QPushButton("搜索")
        self._btn.clicked.connect(self._do_search)
        self._btn.setStyleSheet(
            "QPushButton { background: #e2e8f0; color: #0f172a; border: 1px solid #cbd5e1; border-radius: 6px; padding: 4px 10px; }"
            "QPushButton:hover { background: #dbe5f1; }"
        )

        row.addWidget(self.input, 1)
        row.addWidget(self._btn)

        nav = QHBoxLayout()
        self._prev_btn = QPushButton("↑")
        self._prev_btn.setFixedSize(28, 24)
        self._prev_btn.clicked.connect(self.prevRequested)
        self._next_btn = QPushButton("↓")
        self._next_btn.setFixedSize(28, 24)
        self._next_btn.clicked.connect(self.nextRequested)
        self._prev_btn.setStyleSheet(
            "QPushButton { background: #e5eefb; color: #0f172a; border: 1px solid #b7c8e6; border-radius: 6px; font-weight: bold; }"
            "QPushButton:hover { background: #d8e7fb; }"
        )
        self._next_btn.setStyleSheet(
            "QPushButton { background: #e5eefb; color: #0f172a; border: 1px solid #b7c8e6; border-radius: 6px; font-weight: bold; }"
            "QPushButton:hover { background: #d8e7fb; }"
        )
        self._counter = QLabel("0/0")
        self._counter.setStyleSheet("color: #0f172a; font-weight: 600;")
        nav.addWidget(self._prev_btn)
        nav.addWidget(self._next_btn)
        nav.addStretch(1)
        nav.addWidget(self._counter)

        box_layout.addLayout(row)
        box_layout.addLayout(nav)

        self._results = QListWidget()
        self._results.itemClicked.connect(self._on_result_clicked)
        self._results.setStyleSheet("QListWidget { border: 1px solid #d5dbe6; border-radius: 6px; background: #ffffff; }")

        close_btn = QPushButton("关闭搜索")
        close_btn.clicked.connect(self.closeRequested)
        close_btn.setStyleSheet(
            "QPushButton { background: #f1f5f9; color: #0f172a; border: 1px solid #cbd5e1; border-radius: 6px; }"
            "QPushButton:hover { background: #e2e8f0; }"
        )

        result_label = QLabel("搜索结果 (单击跳转):")
        box_layout.addWidget(result_label)
        box_layout.addWidget(self._results, 1)
        box_layout.addWidget(close_btn)
        layout.addWidget(box, 1)

        self.setStyleSheet(
            "QWidget#SearchPanel { background: white; border: 1px solid #c8d7e9; border-radius: 8px; }"
            "QListWidget::item { color: #0f172a; }"
        )
        self.hide()

    def set_results(self, matches: list[tuple[int, int, str]]):
        self._results.clear()
        if not matches:
            label = QLabel("未找到结果。")
            label.setStyleSheet("color: #334155; background: transparent; padding: 6px;")
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
            label.setStyleSheet("padding: 8px; border-bottom: 1px solid #dbe3ef; background: #f8fafc; color: #0f172a;")
            item.setSizeHint(label.sizeHint())
            self._results.addItem(item)
            self._results.setItemWidget(item, label)

    def set_counter(self, current: int, total: int) -> None:
        if total <= 0:
            self._counter.setText("0/0")
            return
        self._counter.setText(f"{current}/{total}")

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
        self._search_matches: list[tuple[int, int, str]] = []
        self._search_idx: int = -1
        self._search_extras: list[QTextEdit.ExtraSelection] = []
        self._annotation_extras: list[QTextEdit.ExtraSelection] = []
        self._annotation_markers: list[QWidget] = []
        self._pending_note_record: dict | None = None
        self._middle_dragging = False
        self._middle_drag_y = 0
        self._middle_drag_current_y = 0
        self._middle_scroll_timer = QTimer(self)
        self._middle_scroll_timer.setInterval(16)
        self._middle_scroll_timer.timeout.connect(self._tick_middle_scroll)
        self._note_preview_popup: NotePreviewPopup | None = None
        self._footnote_popup: FootnotePopup | None = None
        self._media_popup: MediaPreviewPopup | None = None
        self._footnote_jump_target: dict | None = None
        self._footnote_return_positions: dict[tuple[int, str], int] = {}
        self._loading_book = False
        self._progress_steps = 1_000_000
        self._paginated_pages: list[tuple[int, int, int, bool]] = []
        self._paginated_current_page = 0
        self._pending_restore_ratio: float | None = None
        self._page_anim_old: QPropertyAnimation | None = None
        self._page_anim_new: QPropertyAnimation | None = None
        self._page_animating = False
        self._flip_old_label: QLabel | None = None
        self._flip_new_label: QLabel | None = None
        self._media_debug_enabled = os.environ.get("STONEREADER_MEDIA_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"}
        self._media_debug_path = Path(__file__).resolve().parents[3] / ".local" / "library" / "media_debug.log"
        self._media_debug_lines: list[str] = []
        self._media_injection_timer = QTimer(self)
        self._media_injection_timer.setInterval(10)
        self._media_injection_timer.timeout.connect(self._process_media_injection_batch)
        self._media_injection_queue: list[dict] = []
        self._media_injection_total = 0
        self._media_injection_done = 0
        self._media_image_cache: dict[str, QImage] = {}

        # Layout Setup
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # 1. Left Sidebar
        self._sidebar = ReaderSidebar()
        self._sidebar.chapterSelected.connect(self._jump_to_chapter)
        self._sidebar.annotationSelected.connect(self._jump_to_annotation)
        self._sidebar.annotationDeleteRequested.connect(self._delete_annotation)
        self._sidebar.exportRequested.connect(self._export_annotations)
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
        self._toggle_sidebar_btn.setStyleSheet(
            "QPushButton { background: transparent; color: rgba(0,0,0,0.6); border: none; border-radius: 4px; }"
            "QPushButton:hover { background: rgba(0,0,0,0.08); }"
        )
        self._toggle_sidebar_btn.setFixedSize(40, 36)
        self._toggle_sidebar_btn.clicked.connect(self._toggle_sidebar)

        self._back_btn = HoverButton("")
        self._back_btn.setIcon(QIcon(_icon_path("back")))
        self._back_btn.setToolTip("返回书架")
        self._back_btn.setFixedSize(40, 36)
        self._back_btn.clicked.connect(self._handle_back)

        self._header_info = QLabel("未打开书籍")
        self._header_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._header_info.setStyleSheet("color: rgba(0, 0, 0, 0.4); font-size: 13px;")

        self._toggle_settings_btn = QPushButton("")
        self._toggle_settings_btn.setIcon(QIcon(_icon_path("settings")))
        self._toggle_settings_btn.setToolTip("显示设置")
        self._toggle_settings_btn.setStyleSheet(
            "QPushButton { background: transparent; color: rgba(0,0,0,0.6); border: none; border-radius: 4px; }"
            "QPushButton:hover { background: rgba(0,0,0,0.08); }"
        )
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
        self._text.viewport().installEventFilter(self)
        
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

        self._progress_slider = ChapterProgressSlider(Qt.Orientation.Horizontal)
        self._progress_slider.setRange(0, self._progress_steps)
        self._progress_slider.setStyleSheet("QSlider::handle:horizontal { background: rgba(0,0,0,0.3); width: 8px; border-radius: 4px; margin: -5px 0; } QSlider::groove:horizontal { background: rgba(0,0,0,0.1); height: 4px; border-radius: 2px; }")
        self._progress_slider.valueChanged.connect(self._on_slider_changed)

        self._progress_label = QLabel("0%")
        self._progress_label.setStyleSheet("color: rgba(0,0,0,0.5);")
        self._page_label = QLabel("")
        self._page_label.setStyleSheet("color: rgba(0,0,0,0.5);")
        self._page_label.hide()

        bottom_bar.addWidget(self._progress_slider, 1)
        bottom_bar.addSpacing(12)
        bottom_bar.addWidget(self._page_label)
        bottom_bar.addSpacing(8)
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
        self._search_panel.prevRequested.connect(self._goto_prev_match)
        self._search_panel.nextRequested.connect(self._goto_next_match)
        self._search_panel.closeRequested.connect(self._close_search_panel)
        shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        shortcut.activated.connect(self._toggle_search)
        self._esc_shortcut = QShortcut(QKeySequence("Esc"), self)
        self._esc_shortcut.activated.connect(self._handle_back)
        self._sc_prev = QShortcut(QKeySequence(self._visual_settings.shortcut_prev), self)
        self._sc_prev.activated.connect(self._go_prev)
        self._sc_next = QShortcut(QKeySequence(self._visual_settings.shortcut_next), self)
        self._sc_next.activated.connect(self._go_next)
        self._media_debug_shortcut = QShortcut(QKeySequence("Ctrl+Shift+I"), self)
        self._media_debug_shortcut.activated.connect(self._show_media_debug_report)

        self._quick_bar = SelectionQuickBar(self)
        self._quick_bar.bookmarkClicked.connect(self._add_bookmark_from_selection)
        self._quick_bar.highlightColorClicked.connect(self._add_highlight_from_selection)
        self._quick_bar.noteClicked.connect(self._add_note_from_selection)

        self._inline_note_editor = InlineNoteEditor(self)
        self._inline_note_editor.submitRequested.connect(self._submit_inline_note)
        self._inline_note_editor.canceled.connect(self._cancel_inline_note)
        self._note_preview_popup = NotePreviewPopup(self)
        self._footnote_popup = FootnotePopup(self)
        self._footnote_popup.jumpRequested.connect(self._jump_to_footnote_content)
        self._media_popup = MediaPreviewPopup(self)

        self.main_layout.addWidget(self._sidebar, 0)
        self.main_layout.addWidget(self.reading_area, 1)
        self.main_layout.addWidget(self._settings_panel, 0)

        self._apply_visual_settings(self._visual_settings)
        if self._media_debug_enabled:
            self._media_debug_log(f"media_debug_enabled=True path={self._media_debug_path}")

    def _media_debug_log(self, message: str) -> None:
        if not self._media_debug_enabled:
            return
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {message}"
        self._media_debug_lines.append(line)
        if len(self._media_debug_lines) > 300:
            self._media_debug_lines = self._media_debug_lines[-300:]
        try:
            self._media_debug_path.parent.mkdir(parents=True, exist_ok=True)
            with self._media_debug_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def _show_media_debug_report(self) -> None:
        if not self._media_debug_enabled:
            QMessageBox.information(
                self,
                "媒体调试",
                "媒体调试未开启。\n\n请先以环境变量 STONEREADER_MEDIA_DEBUG=1 启动程序后重现问题。",
            )
            return
        tail = self._media_debug_lines[-30:]
        body = "\n".join(tail) if tail else "(当前会话暂无媒体调试日志)"
        QMessageBox.information(
            self,
            "媒体调试（最近30条）",
            f"日志文件: {self._media_debug_path}\n\n{body}",
        )

    def _toggle_settings(self) -> None:
        self._settings_panel.setVisible(not self._settings_panel.isVisible())

    def _toggle_sidebar(self) -> None:
        self._sidebar.setVisible(not self._sidebar.isVisible())

    def _handle_back(self) -> None:
        self._hide_transient_popups()
        snapshot = self.current_progress_snapshot()
        if snapshot is not None:
            self.progressChanged.emit(snapshot[0], snapshot[1])
        if self._settings_panel.isVisible():
            self._settings_panel.hide()
            return
        if self._sidebar.isVisible():
            self._sidebar.hide()
            return
        self.backRequested.emit()

    def _hide_transient_popups(self) -> None:
        if self._quick_bar is not None and self._quick_bar.isVisible():
            self._quick_bar.hide()
        if self._inline_note_editor is not None and self._inline_note_editor.isVisible():
            self._inline_note_editor.hide()
        if self._note_preview_popup is not None and self._note_preview_popup.isVisible():
            self._note_preview_popup.hide()
        if self._footnote_popup is not None and self._footnote_popup.isVisible():
            self._footnote_popup.hide()
        if self._media_popup is not None and self._media_popup.isVisible():
            self._media_popup.hide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._clear_page_animation_overlays()
        self._update_line_wrap_width()
        if self._visual_settings.reading_mode == "paginated":
            self._build_paginated_pages()
            self._apply_pending_restore_ratio()
        self._refresh_annotation_visuals()
        self._reposition_search_panel()
        if self._note_preview_popup and self._note_preview_popup.isVisible():
            self._note_preview_popup.hide()
            def showEvent(self, event) -> None:
                super().showEvent(event)
                self._apply_pending_restore_ratio()

        if self._footnote_popup and self._footnote_popup.isVisible():
            self._footnote_popup.hide()
        if self._media_popup and self._media_popup.isVisible():
            self._media_popup.hide()

    def eventFilter(self, obj, event):
        if obj is self._text.viewport():
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                gp = self._text.viewport().mapToGlobal(event.position().toPoint())
                local = self.mapFromGlobal(gp)
                hit_footnote = self._footnote_popup is not None and self._footnote_popup.isVisible() and self._footnote_popup.geometry().contains(local)
                hit_media = self._media_popup is not None and self._media_popup.isVisible() and self._media_popup.geometry().contains(local)
                hit_note = self._note_preview_popup is not None and self._note_preview_popup.isVisible() and self._note_preview_popup.geometry().contains(local)
                if not (hit_footnote or hit_media or hit_note):
                    self._hide_transient_popups()
            if event.type() == QEvent.Type.Wheel and self._visual_settings.reading_mode == "paginated":
                if event.angleDelta().y() < 0:
                    self._go_next()
                elif event.angleDelta().y() > 0:
                    self._go_prev()
                return True
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.MiddleButton:
                self._middle_dragging = True
                self._middle_drag_y = event.globalPosition().toPoint().y()
                self._middle_drag_current_y = self._middle_drag_y
                self._middle_scroll_timer.start()
                self._text.viewport().setCursor(Qt.CursorShape.SizeVerCursor)
                return True
            if event.type() == QEvent.Type.MouseMove and self._middle_dragging:
                self._middle_drag_current_y = event.globalPosition().toPoint().y()
                return True
            if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                if self._try_open_builtin_footnote(event.position().toPoint()):
                    return True
                if self._try_open_media_marker(event.position().toPoint()):
                    return True
            if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.MiddleButton:
                self._middle_dragging = False
                self._middle_scroll_timer.stop()
                self._text.viewport().unsetCursor()
                return True
        return super().eventFilter(obj, event)

    def _try_open_builtin_footnote(self, pos: QPoint) -> bool:
        cursor = self._text.cursorForPosition(pos)
        if cursor.hasSelection():
            return False
        plain = self._text.toPlainText()
        if not plain:
            return False
        cp = cursor.position()
        left = max(0, cp - 12)
        right = min(len(plain), cp + 12)
        snippet = plain[left:right]

        token = ""
        num = ""
        for m in re.finditer(r"\[([^\[\]\s]{1,32})\]", snippet):
            gs = left + m.start()
            ge = left + m.end()
            if gs <= cp <= ge:
                num = m.group(1)
                token = m.group(0)
                break

        chapter_idx = self._current_chapter_idx
        if self._visual_settings.reading_mode == "full_scroll":
            chapter_idx = self._chapter_index_from_doc_pos(cp)
        chapter_idx = max(0, min(chapter_idx, len(self._chapters) - 1))
        ch = self._chapters[chapter_idx]

        if not token:
            # AZW3 常见：正文中是裸数字上标（非 [1] 形式）。
            num_re = re.compile(r"(?<!\d)(\d{1,4})(?!\d)")
            for m in num_re.finditer(snippet):
                gs = left + m.start(1)
                ge = left + m.end(1)
                if gs <= cp <= ge:
                    cand = m.group(1)
                    if cand in ch.footnotes:
                        num = cand
                        token = f"[{cand}]"
                        break
        if not token:
            return False

        key = (chapter_idx, token)
        note_text = ch.footnotes.get(token) or ch.footnotes.get(num)
        if not note_text:
            return False

        jump_pos = self._find_footnote_anchor_pos(plain, token, num, cp)
        if jump_pos < 0 and key in self._footnote_return_positions:
            jump_pos = int(self._footnote_return_positions[key])

        self._footnote_jump_target = {
            "chapter_idx": chapter_idx,
            "token": token,
            "jump_pos": jump_pos,
            "return_pos": cp,
        }

        if self._footnote_popup is not None:
            global_pos = self._text.viewport().mapToGlobal(pos)
            self._footnote_popup.show_footnote(global_pos, token, note_text, jump_pos >= 0)
        return True

    def _find_footnote_anchor_pos(self, plain: str, token: str, num: str, origin_pos: int) -> int:
        if not plain:
            return -1

        positions: list[int] = [m.start() for m in re.finditer(re.escape(token), plain)]
        if not positions and num:
            positions = [m.start() for m in re.finditer(rf"\b{re.escape(num)}\b", plain)]
        if not positions:
            return -1

        # Avoid jumping to the same inline marker that the user just clicked.
        far_positions = [p for p in sorted(set(positions)) if abs(p - origin_pos) > 24]
        if not far_positions:
            return -1

        after = [p for p in far_positions if p > origin_pos]
        if after:
            return after[0]
        return far_positions[-1]

    def _jump_to_footnote_content(self) -> None:
        target = self._footnote_jump_target
        if not target:
            return
        jump_pos = int(target.get("jump_pos", -1))
        if jump_pos < 0:
            return
        chapter_idx = int(target.get("chapter_idx", self._current_chapter_idx))
        token = str(target.get("token", ""))
        return_pos = int(target.get("return_pos", 0))

        self._footnote_return_positions[(chapter_idx, token)] = return_pos
        c = self._text.textCursor()
        c.setPosition(max(0, min(jump_pos, max(0, self._text.document().characterCount() - 1))))
        self._text.setTextCursor(c)
        self._text.ensureCursorVisible()
        if self._footnote_popup is not None:
            self._footnote_popup.hide()

    def _try_open_media_marker(self, pos: QPoint) -> bool:
        cursor = self._text.cursorForPosition(pos)
        if cursor.hasSelection():
            return False
        plain = self._text.toPlainText()
        if not plain:
            return False
        cp = cursor.position()
        left = max(0, cp - 16)
        right = min(len(plain), cp + 16)
        snippet = plain[left:right]
        token = ""
        for m in re.finditer(r"\[图(\d{1,4})\]", snippet):
            gs = left + m.start()
            ge = left + m.end()
            if gs <= cp <= ge:
                token = m.group(0)
                break
        if not token:
            return False

        chapter_idx = self._current_chapter_idx
        if self._visual_settings.reading_mode == "full_scroll":
            chapter_idx = self._chapter_index_from_doc_pos(cp)
        chapter_idx = max(0, min(chapter_idx, len(self._chapters) - 1))
        ch = self._chapters[chapter_idx]
        entry = next((m for m in ch.media if str(m.get("token", "")) == token), None)
        if not entry:
            return False
        if self._media_popup is None:
            return False
        global_pos = self._text.viewport().mapToGlobal(pos)
        self._media_popup.show_media(global_pos, token, str(entry.get("alt", "")), str(entry.get("data_url", "")))
        return True

    def _chapter_index_from_doc_pos(self, doc_pos: int) -> int:
        offset = 0
        for i, ch in enumerate(self._chapters):
            start = offset
            end = start + len(ch.text)
            if start <= doc_pos <= end:
                return i
            offset = end + (3 if i < len(self._chapters) - 1 else 0)
        return max(0, min(self._current_chapter_idx, len(self._chapters) - 1))

    def _tick_middle_scroll(self) -> None:
        if not self._middle_dragging:
            return
        delta = self._middle_drag_current_y - self._middle_drag_y
        if abs(delta) < 1:
            return
        gain = max(2, int(self._visual_settings.middle_scroll_gain_percent))
        speed = int(delta * (gain / 100.0))
        if speed == 0:
            speed = 1 if delta > 0 else -1
        cap = max(8, int(self._visual_settings.middle_scroll_speed_cap))
        speed = max(-cap, min(cap, speed))
        bar = self._text.verticalScrollBar()
        bar.setValue(bar.value() + speed)

    def _clear_page_animation_overlays(self) -> None:
        if self._page_anim_old is not None:
            try:
                self._page_anim_old.stop()
            except Exception:
                pass
            self._page_anim_old = None
        if self._page_anim_new is not None:
            try:
                self._page_anim_new.stop()
            except Exception:
                pass
            self._page_anim_new = None
        if self._flip_old_label is not None:
            self._flip_old_label.deleteLater()
            self._flip_old_label = None
        if self._flip_new_label is not None:
            self._flip_new_label.deleteLater()
            self._flip_new_label = None
        self._page_animating = False

    def load_book(self, book: Book) -> None:
        chapters = self.parse_book_file(book.file_path or "")
        self.load_book_with_chapters(book, chapters)

    @staticmethod
    def parse_book_file(file_path: str, progress: Callable[[int, str], None] | None = None) -> list[ChapterItem]:
        if not file_path:
            return [ChapterItem("全文", "该书籍没有关联本地文件路径。")]

        path = Path(file_path)
        ext = path.suffix.lower()
        if ext == ".txt":
            content = ReaderView._read_txt_raw_static(path)
            chapters = parse_txt(content)
        elif ext == ".epub":
            chapters = parse_epub(str(path), progress=progress)
        elif ext in {".mobi", ".azw3"}:
            chapters = parse_mobi(str(path), progress=progress)
        else:
            chapters = [ChapterItem("格式不支持", f"当前不支持 {ext} 格式解析。")]

        ReaderView._format_chapters_static(chapters)
        return chapters

    def load_book_with_chapters(self, book: Book, chapters: list[ChapterItem]) -> None:
        self._loading_book = True
        try:
            self._clear_page_animation_overlays()
            self._hide_transient_popups()
            self._book = book
            self._bookmarks = list(getattr(book, "bookmarks", []))
            self._highlights = list(getattr(book, "highlights", []))
            self._notes = list(getattr(book, "notes", []))
            self._set_header_text()
            self._text.clear()

            self._chapters = chapters if chapters else [ChapterItem("全文", "未解析到可阅读内容。")]
            self._finish_load(book.read_progress)
        finally:
            self._loading_book = False
            self._update_progress_display(self._current_global_ratio())

    def _read_txt_raw(self, path: Path) -> str:
        return self._read_txt_raw_static(path)

    @staticmethod
    def _read_txt_raw_static(path: Path) -> str:
        for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk"):
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
            except OSError as exc:
                return f"读取失败: {exc}"
        return "读取失败: 编码不受支持。"

    def _format_chapters(self, chapters: list[ChapterItem]):
        self._format_chapters_static(chapters)

    @staticmethod
    def _format_chapters_static(chapters: list[ChapterItem]):
        """Light normalization while preserving parser-produced paragraph semantics."""
        for ch in chapters:
            lines = [line.rstrip() for line in ch.text.splitlines()]
            text = "\n".join(lines).strip()
            text = re.sub(r"\n{3,}", "\n\n", text)
            ch.text = text

    def _finish_load(self, saved_progress: float):
        self._sidebar.populate_toc(self._chapters)
        if self._media_debug_enabled:
            self._media_debug_log(f"load_book: chapters={len(self._chapters)}")
            for idx, ch in enumerate(self._chapters):
                media_count = len(ch.media)
                if media_count <= 0:
                    continue
                self._media_debug_log(f"chapter[{idx}] title={ch.title!r} media_count={media_count}")
                for mi, m in enumerate(ch.media):
                    token = str(m.get("token", ""))
                    src = str(m.get("src", ""))
                    data_url = str(m.get("data_url", ""))
                    has_data = bool(data_url)
                    mime_hint = data_url.split(";", 1)[0] if data_url.startswith("data:") else ""
                    self._media_debug_log(
                        f"chapter[{idx}] media[{mi}] token={token!r} src={src!r} has_data_url={has_data} mime={mime_hint!r}"
                    )
        self._sidebar.populate_annotations(self._bookmarks, self._highlights, self._notes)
        self._update_chapter_markers()
        self._current_chapter_idx = 0
        self._render_current_mode()
        self._pending_restore_ratio = min(max(saved_progress, 0.0), 1.0)
        QTimer.singleShot(0, self._apply_pending_restore_ratio)

    def _apply_pending_restore_ratio(self) -> None:
        if self._pending_restore_ratio is None:
            return
        ratio = self._pending_restore_ratio
        self._pending_restore_ratio = None
        self._set_progress(ratio)

    def _chapter_weights(self) -> list[int]:
        if self._visual_settings.reading_mode == "paginated":
            if not self._paginated_pages:
                return [1]
            return [1 for _ in self._paginated_pages]
        if not self._chapters:
            return [1]
        return [max(1, len(ch.text)) for ch in self._chapters]

    def _current_global_ratio(self) -> float:
        if not self._chapters:
            return 0.0
        mode = self._visual_settings.reading_mode
        if mode == "paginated":
            total = max(1, len(self._paginated_pages))
            if total == 1:
                return 0.0
            return min(1.0, max(0.0, self._paginated_current_page / (total - 1)))
        if mode == "full_scroll":
            bar = self._text.verticalScrollBar()
            max_scroll = max(bar.maximum(), 1)
            return min(1.0, max(0.0, bar.value() / max_scroll))

        weights = self._chapter_weights()
        total = max(1, sum(weights))
        idx = max(0, min(self._current_chapter_idx, len(weights) - 1))
        prefix = sum(weights[:idx])
        bar = self._text.verticalScrollBar()
        local_ratio = bar.value() / max(bar.maximum(), 1)
        local_ratio = min(1.0, max(0.0, local_ratio))
        return min(1.0, max(0.0, (prefix + local_ratio * weights[idx]) / total))

    def _seek_by_global_ratio(self, ratio: float) -> None:
        if not self._chapters:
            return
        ratio = min(1.0, max(0.0, ratio))
        mode = self._visual_settings.reading_mode

        if mode == "paginated":
            if not self._paginated_pages:
                self._build_paginated_pages()
            total = len(self._paginated_pages)
            if total <= 0:
                return
            if total == 1:
                target_page = 0
            else:
                target_page = int(round(ratio * (total - 1)))
            self._set_paginated_page(target_page, animate_dir=0)
            return

        if mode == "full_scroll":
            bar = self._text.verticalScrollBar()
            bar.setValue(int(ratio * max(bar.maximum(), 1)))
            return

        weights = self._chapter_weights()
        total = max(1, sum(weights))
        absolute = ratio * total
        acc = 0.0
        target_idx = 0
        intra_ratio = 0.0
        for idx, w in enumerate(weights):
            upper = acc + w
            if absolute < upper or idx == len(weights) - 1:
                target_idx = idx
                intra_ratio = (absolute - acc) / max(1, w)
                intra_ratio = min(1.0, max(0.0, intra_ratio))
                break
            acc += w

        if target_idx != self._current_chapter_idx:
            self._current_chapter_idx = target_idx
            self._render_current_mode()
        bar = self._text.verticalScrollBar()
        bar.setValue(int(round(intra_ratio * max(bar.maximum(), 1))))
        if mode == "paginated":
            self._update_paginated_page_label()

    def _compute_wrapped_line_ranges(self, text: str, max_width_px: int, font: QFont) -> list[tuple[int, int]]:
        from PyQt6.QtGui import QTextLayout

        ranges: list[tuple[int, int]] = []
        offset = 0
        paragraphs = text.split("\n")
        for idx, para in enumerate(paragraphs):
            base = offset
            if para == "":
                ranges.append((base, base))
                if idx < len(paragraphs) - 1:
                    offset += 1
                continue

            layout = QTextLayout(para, font)
            layout.beginLayout()
            while True:
                line = layout.createLine()
                if not line.isValid():
                    break
                line.setLineWidth(float(max_width_px))
                s = int(line.textStart())
                l = int(line.textLength())
                ranges.append((base + s, base + s + l))
            layout.endLayout()

            offset += len(para)
            if idx < len(paragraphs) - 1:
                offset += 1
        return ranges

    def _effective_content_metrics(self) -> tuple[int, int]:
        max_w = self.reading_area.width()
        content_w = max(220, int(max_w * self._visual_settings.line_width_percent / 100))
        font_px = max(10, int(self._visual_settings.font_size * 1.35))
        line_height = max(16, int(font_px * self._visual_settings.line_spacing_percent / 100))
        return content_w, line_height

    def _build_paginated_pages(self) -> None:
        if self._visual_settings.reading_mode != "paginated":
            self._paginated_pages = []
            self._paginated_current_page = 0
            self._update_paginated_page_label()
            return

        content_w, line_h = self._effective_content_metrics()
        page_h = max(120, self._text.viewport().height())
        page_lines = max(4, page_h // max(1, line_h))
        font = self._text.font()

        pages: list[tuple[int, int, int, bool]] = []
        for ci, ch in enumerate(self._chapters):
            text = ch.text or ""
            if not text:
                pages.append((ci, 0, 0, True))
                continue
            line_ranges = self._compute_wrapped_line_ranges(text, content_w, font)
            if not line_ranges:
                pages.append((ci, 0, len(text), True))
                continue

            first = True
            idx = 0
            while idx < len(line_ranges):
                cap = page_lines - 2 if first else page_lines
                cap = max(1, cap)
                end_line_idx = min(len(line_ranges), idx + cap)
                start_off = line_ranges[idx][0]
                end_off = line_ranges[end_line_idx - 1][1]
                pages.append((ci, start_off, end_off, first))
                idx = end_line_idx
                first = False

        self._paginated_pages = pages if pages else [(0, 0, 0, True)]
        self._paginated_current_page = min(max(self._paginated_current_page, 0), len(self._paginated_pages) - 1)
        self._update_paginated_page_label()

    def _render_paginated_page_text(self, page_idx: int) -> str:
        if not self._paginated_pages:
            return ""
        page_idx = min(max(page_idx, 0), len(self._paginated_pages) - 1)
        chapter_idx, start, end, is_first = self._paginated_pages[page_idx]
        ch = self._chapters[chapter_idx]
        body = (ch.text or "")[start:end]
        return body

    def _decode_data_url_image(self, data_url: str) -> QImage | None:
        cached = self._media_image_cache.get(data_url)
        if cached is not None:
            return cached
        if not data_url.startswith("data:") or ";base64," not in data_url:
            self._media_debug_log("decode_fail: invalid_data_url_prefix_or_format")
            return None
        payload = data_url.split(";base64,", 1)[1]
        try:
            raw = base64.b64decode(payload)
        except Exception as exc:
            self._media_debug_log(f"decode_fail: base64_error={exc}")
            return None
        img = QImage()
        if not img.loadFromData(raw):
            self._media_debug_log("decode_fail: qimage_load_from_data_failed")
            return None
        self._media_debug_log(f"decode_ok: size={img.width()}x{img.height()} bytes={len(raw)}")
        self._media_image_cache[data_url] = img
        return img

    def _collect_visible_media_entries(self) -> list[dict]:
        doc_text = self._text.toPlainText()
        if not doc_text:
            return []

        entries: list[dict] = []
        mode = self._visual_settings.reading_mode
        scan_pos = 0

        if mode == "full_scroll":
            for ch in self._chapters:
                for m in ch.media:
                    token = str(m.get("token", ""))
                    alt = str(m.get("alt", ""))
                    data_url = str(m.get("data_url", ""))
                    if not token or not data_url:
                        self._media_debug_log(f"collect_skip: token_or_data_missing token={token!r} has_data={bool(data_url)}")
                        continue
                    pos = doc_text.find(token, scan_pos)
                    if pos < 0:
                        pos = doc_text.find(token)
                    if pos < 0:
                        self._media_debug_log(f"collect_skip: token_not_found_in_doc token={token!r}")
                        continue
                    entries.append({"token": token, "alt": alt, "data_url": data_url, "pos": pos})
                    self._media_debug_log(f"collect_ok: token={token!r} pos={pos} alt={alt!r}")
                    scan_pos = pos + len(token)
            return entries

        # chapter_scroll / paginated: only current chapter media are relevant
        chapter_idx = self._current_chapter_idx
        if mode == "paginated" and self._paginated_pages:
            chapter_idx = self._paginated_pages[self._paginated_current_page][0]
        chapter_idx = max(0, min(chapter_idx, len(self._chapters) - 1))
        ch = self._chapters[chapter_idx]
        for m in ch.media:
            token = str(m.get("token", ""))
            alt = str(m.get("alt", ""))
            data_url = str(m.get("data_url", ""))
            if not token or not data_url:
                self._media_debug_log(f"collect_skip: token_or_data_missing token={token!r} has_data={bool(data_url)}")
                continue
            text_pos = m.get("text_pos")
            pos = -1
            if isinstance(text_pos, int):
                tpos = max(0, min(text_pos, max(0, len(doc_text) - len(token))))
                if doc_text[tpos:tpos + len(token)] == token:
                    pos = tpos
            if pos < 0:
                pos = doc_text.find(token, scan_pos)
            if pos < 0:
                pos = doc_text.find(token)
            if pos < 0:
                self._media_debug_log(f"collect_skip: token_not_found_in_doc token={token!r}")
                continue
            entries.append({"token": token, "alt": alt, "data_url": data_url, "pos": pos})
            self._media_debug_log(f"collect_ok: token={token!r} pos={pos} alt={alt!r}")
            scan_pos = pos + len(token)
        return entries

    def _cancel_media_injection(self) -> None:
        if self._media_injection_timer.isActive():
            self._media_injection_timer.stop()
        self._media_injection_queue = []
        self._media_injection_total = 0
        self._media_injection_done = 0

    def _insert_media_entry(self, entry: dict) -> bool:
        token = str(entry.get("token", ""))
        alt = str(entry.get("alt", "")).strip()
        data_url = str(entry.get("data_url", ""))
        pos = int(entry.get("pos", -1))
        if not token or pos < 0 or not data_url:
            self._media_debug_log(f"inject_skip: bad_entry token={token!r} pos={pos} has_data={bool(data_url)}")
            return False

        img = self._decode_data_url_image(data_url)
        if img is None:
            self._media_debug_log(f"inject_skip: decode_none token={token!r} pos={pos}")
            return False

        inline = bool(entry.get("inline", False))

        doc = self._text.document()
        max_w = max(120, int(self._text.viewport().width() * 0.72))
        start = max(0, min(pos, max(0, doc.characterCount() - 1)))
        end = max(start, min(start + len(token), max(0, doc.characterCount() - 1)))
        found = QTextCursor(doc)
        found.setPosition(start)
        found.setPosition(end, QTextCursor.MoveMode.KeepAnchor)

        if found.selectedText() != token:
            located = doc.find(token, start)
            if located.isNull():
                located = doc.find(token)
            if located.isNull():
                self._media_debug_log(f"inject_skip: token_not_found token={token!r} pos={pos}")
                return False
            found = located

        name = f"inline-media-{hash((token, pos)) & 0xfffffff}"
        doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl(name), img)

        fmt = QTextImageFormat()
        fmt.setName(name)
        if inline:
            base_h = max(14, int(self._visual_settings.font_size * 1.35))
            h = base_h
            w = int(h * img.width() / img.height()) if img.height() > 0 else h
            w = max(base_h, min(base_h * 4, w))
            fmt.setWidth(float(w))
            fmt.setHeight(float(h))
            found.insertImage(fmt)
            self._media_debug_log(
                f"inject_ok_inline: token={token!r} pos={pos} img={img.width()}x{img.height()} render={w}x{h}"
            )
        else:
            w = min(max_w, img.width())
            h = int(w * img.height() / img.width()) if img.width() > 0 else 100
            fmt.setWidth(float(max(80, w)))
            fmt.setHeight(float(max(50, h)))
            found.insertText("\n")
            found.insertImage(fmt)
            if alt:
                found.insertText(f"\n{alt}")
            found.insertText("\n")
            self._media_debug_log(f"inject_ok: token={token!r} pos={pos} img={img.width()}x{img.height()} alt={alt!r}")
        return True

    def _process_media_injection_batch(self) -> None:
        if not self._media_injection_queue:
            if self._media_injection_timer.isActive():
                self._media_injection_timer.stop()
            remaining_tokens = re.findall(r"\[图\d{1,4}\]", self._text.toPlainText())
            self._media_debug_log(
                f"inject_summary: replaced={self._media_injection_done} remaining_tokens={sorted(set(remaining_tokens))}"
            )
            self._update_progress_display(self._current_global_ratio())
            return

        batch_size = 2
        for _ in range(batch_size):
            if not self._media_injection_queue:
                break
            entry = self._media_injection_queue.pop(0)
            if self._insert_media_entry(entry):
                self._media_injection_done += 1

        self._update_progress_display(self._current_global_ratio())

    def _start_media_injection(self, entries: list[dict]) -> None:
        self._cancel_media_injection()
        if not entries:
            remaining_tokens = re.findall(r"\[图\d{1,4}\]", self._text.toPlainText())
            if remaining_tokens:
                self._media_debug_log(
                    f"inject_none: no_resolved_entries remaining_tokens={sorted(set(remaining_tokens))}"
                )
            self._update_progress_display(self._current_global_ratio())
            return

        self._media_injection_queue = sorted(entries, key=lambda x: int(x.get("pos", -1)), reverse=True)
        self._media_injection_total = len(self._media_injection_queue)
        self._media_injection_done = 0
        self._media_debug_log(f"inject_start: total={self._media_injection_total}")
        self._process_media_injection_batch()
        if self._media_injection_queue:
            self._media_injection_timer.start()

    def _inject_inline_media(self) -> None:
        entries = self._collect_visible_media_entries()
        self._start_media_injection(entries)

    def _reset_text_char_format_state(self) -> None:
        doc = self._text.document()
        if doc is None:
            return
        doc.setDefaultFont(self._text.font())
        fmt = QTextCharFormat()
        fmt.setFont(self._text.font())
        fmt.setForeground(QColor(self._visual_settings.text_color))
        fmt.setFontUnderline(False)
        self._text.setCurrentCharFormat(fmt)

    def _style_jumpable_tokens(self) -> None:
        text = self._text.toPlainText()
        if not text:
            return
        fmt = QTextCharFormat()
        fmt.setFontUnderline(True)
        fmt.setForeground(QColor("#1d4ed8"))
        doc = self._text.document()
        token_re = QRegularExpression(r"\[(\d{1,4})\]")
        c = QTextCursor(doc)
        while True:
            c = doc.find(token_re, c)
            if c.isNull():
                break
            c.mergeCharFormat(fmt)
        self._reset_text_char_format_state()

    def _apply_inline_styles_to_view(self) -> None:
        if not self._chapters:
            return
        doc = self._text.document()
        if doc is None:
            return

        mode = self._visual_settings.reading_mode
        mappings: list[tuple[int, int, dict]] = []

        if mode == "full_scroll":
            offset = 0
            for i, ch in enumerate(self._chapters):
                body_base = offset
                for span in ch.inline_styles:
                    start = int(span.get("start", 0))
                    end = int(span.get("end", start))
                    if end > start:
                        mappings.append((body_base + start, body_base + end, span))
                offset = body_base + len(ch.text)
                if i < len(self._chapters) - 1:
                    offset += 3
        elif mode == "chapter_scroll":
            ch = self._chapters[self._current_chapter_idx]
            body_base = 0
            for span in ch.inline_styles:
                start = int(span.get("start", 0))
                end = int(span.get("end", start))
                if end > start:
                    mappings.append((body_base + start, body_base + end, span))
        elif mode == "paginated" and self._paginated_pages:
            chapter_idx, slice_start, slice_end, is_first = self._paginated_pages[self._paginated_current_page]
            ch = self._chapters[chapter_idx]
            body_base = 0
            for span in ch.inline_styles:
                start = int(span.get("start", 0))
                end = int(span.get("end", start))
                if end <= start:
                    continue
                if end <= slice_start or start >= slice_end:
                    continue
                mapped_start = body_base + max(0, start - slice_start)
                mapped_end = body_base + min(slice_end - slice_start, end - slice_start)
                if mapped_end > mapped_start:
                    mappings.append((mapped_start, mapped_end, span))

        doc_len = max(0, doc.characterCount() - 1)
        base_size = max(10, int(self._visual_settings.font_size))
        for start, end, span in mappings:
            s = max(0, min(start, doc_len))
            e = max(s + 1, min(end, doc_len))
            if e <= s:
                continue
            fmt = QTextCharFormat()
            if bool(span.get("bold", False)):
                fmt.setFontWeight(QFont.Weight.Bold)
            if bool(span.get("italic", False)):
                fmt.setFontItalic(True)
            if bool(span.get("underline", False)):
                fmt.setFontUnderline(True)
            if bool(span.get("strike", False)):
                fmt.setFontStrikeOut(True)
            size_factor = float(span.get("size_factor", 1.0))
            if abs(size_factor - 1.0) > 0.01:
                fmt.setFontPointSize(max(8.0, base_size * size_factor))
            color = str(span.get("color", "") or "").strip()
            if color:
                fmt.setForeground(QColor(color))
            bg = str(span.get("background", "") or "").strip()
            if bg:
                fmt.setBackground(QColor(bg))
            if bool(span.get("monospace", False)):
                mono = QFont("Consolas")
                fmt.setFontFamilies([mono.family(), "Courier New"])
            cur = QTextCursor(doc)
            cur.setPosition(s)
            cur.setPosition(e, QTextCursor.MoveMode.KeepAnchor)
            cur.mergeCharFormat(fmt)

    def _play_page_flip_animation(self, old_pix: QPixmap, new_pix: QPixmap, direction: int) -> None:
        viewport = self._text.viewport()
        self._clear_page_animation_overlays()
        w = viewport.width()
        h = viewport.height()
        if w <= 0 or h <= 0:
            return

        old_label = QLabel(viewport)
        old_label.setPixmap(old_pix)
        old_label.setGeometry(0, 0, w, h)
        old_label.show()

        new_label = QLabel(viewport)
        new_label.setPixmap(new_pix)
        start_new_x = w if direction > 0 else -w
        new_label.setGeometry(start_new_x, 0, w, h)
        new_label.show()
        self._flip_old_label = old_label
        self._flip_new_label = new_label

        self._page_animating = True
        self._page_anim_old = QPropertyAnimation(old_label, b"geometry", self)
        self._page_anim_new = QPropertyAnimation(new_label, b"geometry", self)

        self._page_anim_old.setDuration(220)
        self._page_anim_new.setDuration(220)
        self._page_anim_old.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._page_anim_new.setEasingCurve(QEasingCurve.Type.InOutCubic)

        end_old_x = -w if direction > 0 else w
        self._page_anim_old.setStartValue(QRect(0, 0, w, h))
        self._page_anim_old.setEndValue(QRect(end_old_x, 0, w, h))
        self._page_anim_new.setStartValue(QRect(start_new_x, 0, w, h))
        self._page_anim_new.setEndValue(QRect(0, 0, w, h))

        def _finish_one() -> None:
            if self._page_anim_old is None or self._page_anim_new is None:
                return
            if self._page_anim_old.state() == QPropertyAnimation.State.Stopped and self._page_anim_new.state() == QPropertyAnimation.State.Stopped:
                self._clear_page_animation_overlays()

        self._page_anim_old.finished.connect(_finish_one)
        self._page_anim_new.finished.connect(_finish_one)
        self._page_anim_old.start()
        self._page_anim_new.start()

    def _set_paginated_page(self, page_idx: int, animate_dir: int = 0) -> None:
        if not self._paginated_pages:
            self._build_paginated_pages()
        if not self._paginated_pages:
            return
        page_idx = min(max(page_idx, 0), len(self._paginated_pages) - 1)

        if animate_dir == 0:
            self._clear_page_animation_overlays()

        old_pix = self._text.viewport().grab() if animate_dir != 0 else QPixmap()
        self._paginated_current_page = page_idx
        text = self._render_paginated_page_text(page_idx)
        self._reset_text_char_format_state()
        self._text.setPlainText(text)
        self._apply_text_metrics()
        self._apply_inline_styles_to_view()
        self._inject_inline_media()
        self._style_jumpable_tokens()
        self._text.verticalScrollBar().setValue(0)
        self._update_paginated_page_label()

        if animate_dir != 0 and not old_pix.isNull():
            new_pix = self._text.viewport().grab()
            self._play_page_flip_animation(old_pix, new_pix, animate_dir)

    def _update_paginated_page_label(self) -> None:
        if self._visual_settings.reading_mode != "paginated":
            self._page_label.hide()
            return
        total = max(1, len(self._paginated_pages))
        current = min(total, max(1, self._paginated_current_page + 1))
        self._page_label.setText(f"{current}/{total} 页")
        self._page_label.show()

    def _snap_paginated_to_nearest(self) -> None:
        if self._visual_settings.reading_mode != "paginated":
            return
        self._update_paginated_page_label()

    def _animate_to_page_index(self, page_idx: int) -> None:
        if not self._paginated_pages:
            return
        target = max(0, min(page_idx, len(self._paginated_pages) - 1))
        if target == self._paginated_current_page:
            self._update_paginated_page_label()
            return
        direction = 1 if target > self._paginated_current_page else -1
        self._set_paginated_page(target, animate_dir=direction)
        self._update_progress_display(self._current_global_ratio())

    def _update_chapter_markers(self) -> None:
        if not self._chapters:
            self._progress_slider.set_markers([])
            return
        markers: list[tuple[float, str]] = []
        total = sum(max(1, len(ch.text)) for ch in self._chapters)
        if total <= 0:
            self._progress_slider.set_markers([])
            return
        acc = 0
        for idx, ch in enumerate(self._chapters[:-1]):
            acc += max(1, len(ch.text))
            markers.append((acc / total, self._chapters[idx + 1].title))
        self._progress_slider.set_markers(markers)

    # ----------------------------------------------------
    # MODE RENDERING & NAVIGATION LOGIC
    # ----------------------------------------------------

    def _render_current_mode(self):
        """Update QTextEdit based on mode vs chapters state."""
        mode = self._visual_settings.reading_mode
        self._clear_page_animation_overlays()
        self._cancel_media_injection()
        self._btn_prev_area.setVisible(mode != "full_scroll")
        self._btn_next_area.setVisible(mode != "full_scroll")
        
        if mode == "full_scroll":
            # Combine all texts
            full_text = "\n\n\n".join([ch.text for ch in self._chapters])
            self._reset_text_char_format_state()
            self._text.setPlainText(full_text)
            self._text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self._apply_text_metrics()
            self._apply_inline_styles_to_view()
            self._inject_inline_media()
            self._style_jumpable_tokens()
        elif mode == "chapter_scroll":
            # Single chapter or Paginated load just the current chapter
            ch = self._chapters[self._current_chapter_idx]
            self._reset_text_char_format_state()
            self._text.setPlainText(ch.text)

            self._text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self._apply_text_metrics()
            self._apply_inline_styles_to_view()
            self._inject_inline_media()
            self._style_jumpable_tokens()
        else:
            self._text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self._build_paginated_pages()
            self._set_paginated_page(self._paginated_current_page, animate_dir=0)

        if mode == "paginated":
            self._build_paginated_pages()
        else:
            self._paginated_pages = []
            self._paginated_current_page = 0
            self._update_paginated_page_label()
        self._update_chapter_markers()
        self._refresh_annotation_visuals()

    def _go_prev(self):
        mode = self._visual_settings.reading_mode
        bar = self._text.verticalScrollBar()
        
        if mode == "paginated":
            if self._paginated_current_page <= 0:
                return
            else:
                self._animate_to_page_index(self._paginated_current_page - 1)
        elif mode == "chapter_scroll":
            if self._current_chapter_idx > 0:
                self._jump_to_chapter(self._current_chapter_idx - 1)
                
    def _go_next(self):
        mode = self._visual_settings.reading_mode
        bar = self._text.verticalScrollBar()
        
        if mode == "paginated":
            if self._paginated_current_page >= len(self._paginated_pages) - 1:
                return
            else:
                self._animate_to_page_index(self._paginated_current_page + 1)
        elif mode == "chapter_scroll":
            if self._current_chapter_idx < len(self._chapters) - 1:
                self._jump_to_chapter(self._current_chapter_idx + 1)

    def _jump_to_chapter(self, index: int) -> None:
        if index < 0 or index >= len(self._chapters):
            return

        mode = self._visual_settings.reading_mode
        if mode == "full_scroll":
            from PyQt6.QtCore import QTimer
            target_str = "\n\n\n".join([ch.text for ch in self._chapters[:index]])
            pos = len(target_str)
            if index > 0: pos += 3
            cursor = self._text.textCursor()
            cursor.setPosition(pos)
            self._text.setTextCursor(cursor)
            self._text.ensureCursorVisible()
            QTimer.singleShot(0, lambda: self._on_scroll_changed(self._text.verticalScrollBar().value()))
        else:
            # Single/Paginated
            if mode == "paginated":
                if not self._paginated_pages:
                    self._build_paginated_pages()
                target_page = next((i for i, p in enumerate(self._paginated_pages) if p[0] == index), None)
                if target_page is None:
                    return
                self._current_chapter_idx = index
                self._set_paginated_page(target_page, animate_dir=0)
                ratio = self._current_global_ratio()
            else:
                self._current_chapter_idx = index
                self._render_current_mode()
                self._text.verticalScrollBar().setValue(0)
                ratio = self._current_global_ratio()
            
            self._syncing = True
            self._progress_slider.setValue(self._slider_value_from_ratio(ratio))
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

        ratio = self._ratio_from_slider_value(value)
        self._syncing = True
        self._seek_by_global_ratio(ratio)
        self._syncing = False
        self._update_progress_display(self._current_global_ratio())

    def _on_scroll_changed(self, value: int) -> None:
        if self._syncing: return

        if self._visual_settings.reading_mode == "paginated":
            self._update_paginated_page_label()

        ratio = self._current_global_ratio()

        self._syncing = True
        self._progress_slider.setValue(self._slider_value_from_ratio(ratio))
        self._syncing = False

        self._update_progress_display(ratio)
        self._refresh_annotation_visuals()

    def _set_progress(self, ratio: float) -> None:
        bounded = min(max(ratio, 0.0), 1.0)
        self._syncing = True
        self._seek_by_global_ratio(bounded)
        self._progress_slider.setValue(self._slider_value_from_ratio(self._current_global_ratio()))
        self._syncing = False
        if self._visual_settings.reading_mode == "paginated":
            if self._paginated_pages:
                self._current_chapter_idx = self._paginated_pages[self._paginated_current_page][0]
        self._update_progress_display(self._current_global_ratio())

    def _slider_value_from_ratio(self, ratio: float) -> int:
        bounded = min(max(ratio, 0.0), 1.0)
        return int(round(bounded * self._progress_steps))

    def _ratio_from_slider_value(self, value: int) -> float:
        if self._progress_steps <= 0:
            return 0.0
        bounded = min(max(value, 0), self._progress_steps)
        return bounded / self._progress_steps

    def current_progress_snapshot(self) -> tuple[str, float] | None:
        if not self._book or not self._book.file_path:
            return None
        return (self._book.file_path, self._current_global_ratio())

    def _update_progress_display(self, ratio: float):
        if not self._chapters:
            self._progress_label.setText(f"{int(ratio * 100)}%")
            return

        ch = self._chapters[max(0, min(self._current_chapter_idx, len(self._chapters) - 1))]
        media_suffix = ""
        if self._media_injection_total > 0:
            media_suffix = f" | 媒体 {self._media_injection_done}/{self._media_injection_total}"
        txt = f"{ch.title} | 全书 {int(ratio * 100)}%{media_suffix}"
        self._set_header_text(ch.title)

        self._progress_label.setText(txt)
        if self._book and self._book.file_path and not self._loading_book:
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
        old_ratio = self._current_global_ratio()
        self._visual_settings = ReaderVisualSettings(
            font_family_zh=settings.font_family_zh,
            font_family_en=settings.font_family_en,
            font_size=settings.font_size,
            line_spacing_percent=settings.line_spacing_percent,
            line_width_percent=settings.line_width_percent,
            text_color=settings.text_color,
            background_color=settings.background_color,
            reading_mode=settings.reading_mode,
            shortcut_prev=settings.shortcut_prev,
            shortcut_next=settings.shortcut_next,
            middle_scroll_speed_cap=settings.middle_scroll_speed_cap,
            middle_scroll_gain_percent=settings.middle_scroll_gain_percent,
        )

        self.reading_area.setStyleSheet(f"QWidget {{ background: {settings.background_color}; color: {settings.text_color}; }}")
        self._apply_text_metrics()

        if hasattr(self, '_sc_prev'):
            self._sc_prev.setKey(QKeySequence(settings.shortcut_prev))
        if hasattr(self, '_sc_next'):
            self._sc_next.setKey(QKeySequence(settings.shortcut_next))

        if old_mode != settings.reading_mode:
            self._render_current_mode()

        self._syncing = True
        self._seek_by_global_ratio(old_ratio)
        self._progress_slider.setValue(self._slider_value_from_ratio(old_ratio))
        self._syncing = False
        self._update_progress_display(old_ratio)

    def _apply_text_metrics(self) -> None:
        s = self._visual_settings
        font = QFont(s.font_family_zh, s.font_size)
        try:
            font.setFamilies([s.font_family_zh, s.font_family_en])
        except AttributeError:
            font.setFamily(s.font_family_zh)
        self._text.setFont(font)

        self._text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._update_line_wrap_width()

        doc = self._text.document()
        if doc and doc.characterCount() > 0:
            cursor = QTextCursor(doc)
            cursor.select(QTextCursor.SelectionType.Document)
            block_format = cursor.blockFormat()
            block_format.setLineHeight(s.line_spacing_percent, 1)
            block_format.setBottomMargin(s.font_size * 0.8)
            cursor.mergeBlockFormat(block_format)

    def _update_line_wrap_width(self) -> None:
        max_w = self.reading_area.width()
        content_w = int(max_w * self._visual_settings.line_width_percent / 100)
        margin = max(0, (max_w - content_w) // 2)
        zh = self._visual_settings.font_family_zh.replace('"', "")
        en = self._visual_settings.font_family_en.replace('"', "")
        
        self._text.setStyleSheet(
            f"QTextEdit {{ "
            f"background: transparent; border: none; selection-background-color: #88a3b9; "
            f"color: {self._visual_settings.text_color}; "
            f"font-size: {self._visual_settings.font_size}pt; "
            f"font-family: '{zh}', '{en}'; "
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
        else:
            menu.addSeparator()
            for kind, label in (("bookmark", "删除附近书签"), ("highlight", "删除附近标记"), ("note", "删除附近笔记")):
                found = self._find_nearest_annotation(kind)
                if found is None:
                    continue
                idx = found
                act = QAction(label, self)
                act.triggered.connect(lambda _=False, k=kind, i=idx: self._delete_annotation(k, i))
                menu.addAction(act)

        menu.exec(self._text.mapToGlobal(pos))

    def _find_nearest_annotation(self, kind: str) -> int | None:
        source = {
            "bookmark": self._bookmarks,
            "highlight": self._highlights,
            "note": self._notes,
        }.get(kind, [])
        if not source:
            return None
        cursor = self._text.textCursor()
        current_chapter = self._current_chapter_idx
        mode = self._visual_settings.reading_mode
        if mode == "full_scroll":
            pos = cursor.position()
            # derive chapter and local position in full-scroll document
            offset = 0
            chapter_idx = 0
            local_pos = 0
            for i, ch in enumerate(self._chapters):
                start = offset
                end = start + len(ch.text)
                if start <= pos <= end:
                    chapter_idx = i
                    local_pos = pos - start
                    break
                offset = end + (3 if i < len(self._chapters) - 1 else 0)
        else:
            chapter_idx = current_chapter
            local_pos = max(0, cursor.position())

        best_idx = None
        best_dist = 10**9
        for idx, rec in enumerate(source):
            if int(rec.get("chapter_index", -1)) != chapter_idx:
                continue
            dist = abs(int(rec.get("local_start", 0)) - local_pos)
            if dist < best_dist:
                best_dist = dist
                best_idx = idx
        if best_idx is None or best_dist > 30:
            return None
        return best_idx

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
                start = offset
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
            local_start = max(0, cursor.selectionStart())

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

    def _add_highlight_from_selection(self, color: str = "#ffef88") -> None:
        rec = self._selection_record()
        if rec is None:
            return
        rec["color"] = color
        self._highlights.append(rec)
        self._after_annotation_changed()

    def _export_annotations(self) -> None:
        if self._book is None:
            return
        default_name = f"{self._book.title}_annotations.json"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出注释",
            default_name,
            "JSON Files (*.json);;Text Files (*.txt)",
        )
        if not path:
            return

        target = Path(path)
        payload = {
            "book": {
                "title": self._book.title,
                "author": self._book.author,
                "file_path": self._book.file_path,
            },
            "bookmarks": self._bookmarks,
            "highlights": self._highlights,
            "notes": self._notes,
        }
        if target.suffix.lower() == ".txt":
            lines: list[str] = [f"书籍: {self._book.title}", f"作者: {self._book.author}", ""]
            lines.append("[书签]")
            for idx, b in enumerate(self._bookmarks, start=1):
                lines.append(f"{idx}. {b.get('chapter_title','')} @ {b.get('local_start',0)} | {b.get('preview','')}")
            lines.append("")
            lines.append("[标记]")
            for idx, h in enumerate(self._highlights, start=1):
                lines.append(
                    f"{idx}. {h.get('chapter_title','')} @ {h.get('local_start',0)} | 颜色: {h.get('color','#ffef88')} | {h.get('preview','')}"
                )
            lines.append("")
            lines.append("[笔记]")
            for idx, n in enumerate(self._notes, start=1):
                lines.append(f"{idx}. {n.get('chapter_title','')} @ {n.get('local_start',0)}")
                lines.append(f"   选中文本: {n.get('preview','')}")
                lines.append(f"   笔记: {n.get('note','')}")
            target.write_text("\n".join(lines), encoding="utf-8")
        else:
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        QMessageBox.information(self, "导出完成", f"已导出到:\n{target}")

    def _add_note_from_selection(self) -> None:
        rec = self._selection_record()
        if rec is None:
            return
        self._pending_note_record = rec
        self._quick_bar.hide()
        cursor = self._text.textCursor()
        start_cursor = QTextCursor(self._text.document())
        start_cursor.setPosition(cursor.selectionStart())
        rect = self._text.cursorRect(start_cursor)
        local = self._text.mapTo(self, rect.bottomLeft())
        x = max(8, min(local.x(), self.width() - 290))
        y = min(self.height() - 180, max(8, local.y() + 10))
        self._inline_note_editor.clear_text()
        self._inline_note_editor.open_at(QPoint(x, y))

    def _submit_inline_note(self, text: str) -> None:
        if self._pending_note_record is None:
            self._inline_note_editor.hide()
            return
        rec = dict(self._pending_note_record)
        rec["note"] = text
        self._notes.append(rec)
        self._pending_note_record = None
        self._inline_note_editor.hide()
        self._after_annotation_changed()

    def _cancel_inline_note(self) -> None:
        self._pending_note_record = None

    def _after_annotation_changed(self) -> None:
        self._quick_bar.hide()
        self._sidebar.populate_annotations(self._bookmarks, self._highlights, self._notes)
        self._refresh_annotation_visuals()
        if self._book and self._book.file_path:
            self.annotationsChanged.emit(self._book.file_path, self._bookmarks, self._highlights, self._notes)

    def _delete_annotation(self, kind: str, idx: int) -> None:
        source = {
            "bookmark": self._bookmarks,
            "highlight": self._highlights,
            "note": self._notes,
        }.get(kind)
        if source is None or idx < 0 or idx >= len(source):
            return
        source.pop(idx)
        self._after_annotation_changed()

    def _refresh_annotation_visuals(self) -> None:
        for marker in self._annotation_markers:
            marker.deleteLater()
        self._annotation_markers.clear()
        self._annotation_extras.clear()

        if not self._chapters:
            self._apply_extra_selections()
            return

        mode = self._visual_settings.reading_mode
        note_fmt = QTextCharFormat()
        note_fmt.setBackground(QColor("#ffe08a"))

        for rec in self._highlights:
            pos = self._annotation_position_in_current_text(rec, mode)
            if pos is None:
                continue
            color = str(rec.get("color", "#ffef88"))
            highlight_fmt = QTextCharFormat()
            highlight_fmt.setBackground(QColor(color))
            start, length = pos
            doc_len = self._text.document().characterCount()
            if start < 0 or start >= doc_len:
                continue
            end_pos = min(start + max(length, 1), max(start + 1, doc_len - 1))
            cur = QTextCursor(self._text.document())
            cur.setPosition(start)
            cur.setPosition(end_pos, QTextCursor.MoveMode.KeepAnchor)
            ex = QTextEdit.ExtraSelection()
            ex.cursor = cur
            ex.format = highlight_fmt
            self._annotation_extras.append(ex)

        marker_map: dict[int, dict] = {}

        for rec in self._notes:
            pos = self._annotation_position_in_current_text(rec, mode)
            if pos is None:
                continue
            start, length = pos
            doc_len = self._text.document().characterCount()
            if start < 0 or start >= doc_len:
                continue
            end_pos = min(start + max(length, 1), max(start + 1, doc_len - 1))
            cur = QTextCursor(self._text.document())
            cur.setPosition(start)
            cur.setPosition(end_pos, QTextCursor.MoveMode.KeepAnchor)
            ex = QTextEdit.ExtraSelection()
            ex.cursor = cur
            ex.format = note_fmt
            self._annotation_extras.append(ex)
            entry = marker_map.setdefault(start, {"bookmark": False, "note": []})
            entry["note"].append(rec.get("note", ""))

        for rec in self._bookmarks:
            pos = self._annotation_position_in_current_text(rec, mode)
            if pos is None:
                continue
            start, _ = pos
            entry = marker_map.setdefault(start, {"bookmark": False, "note": []})
            entry["bookmark"] = True

        for pos, info in marker_map.items():
            self._add_marker_widget(pos, bool(info["bookmark"]), info["note"])

        self._apply_extra_selections()

    def _annotation_position_in_current_text(self, rec: dict, mode: str) -> tuple[int, int] | None:
        chapter_idx = int(rec.get("chapter_index", -1))
        if chapter_idx < 0 or chapter_idx >= len(self._chapters):
            return None
        local_start = int(rec.get("local_start", 0))
        selected = rec.get("selected_text", "")
        length = max(len(selected), 1)

        if mode == "full_scroll":
            offset = 0
            for i, ch in enumerate(self._chapters):
                if i == chapter_idx:
                    return (offset + local_start, length)
                offset += len(ch.text)
                if i < len(self._chapters) - 1:
                    offset += 3
            return None

        if chapter_idx != self._current_chapter_idx:
            return None
        base = 0
        return (base + local_start, length)

    def _add_marker_widget(self, doc_pos: int, has_bookmark: bool, notes: list[str]) -> None:
        cur = QTextCursor(self._text.document())
        cur.setPosition(max(0, doc_pos))
        rect = self._text.cursorRect(cur)
        panel = QWidget(self._text.viewport())
        row = QHBoxLayout(panel)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(1)

        if has_bookmark:
            bm_btn = QToolButton(panel)
            bm_btn.setIcon(QIcon(_icon_path("bookmark")))
            bm_btn.setIconSize(QSize(12, 12))
            bm_btn.setToolTip("书签")
            bm_btn.setStyleSheet("QToolButton { border: none; padding: 0px; background: transparent; }")
            row.addWidget(bm_btn)

        if notes:
            note_btn = QToolButton(panel)
            note_btn.setIcon(QIcon(_icon_path("note")))
            note_btn.setIconSize(QSize(12, 12))
            note_btn.setToolTip("笔记")
            note_btn.setStyleSheet("QToolButton { border: none; padding: 0px; background: transparent; }")
            merged = "\n\n".join([n for n in notes if n])
            note_btn.clicked.connect(lambda _=False, text=merged, btn=note_btn: self._show_note_popup(btn, text))
            row.addWidget(note_btn)

        panel.adjustSize()
        x = max(2, rect.x() - panel.width() - 4)
        y = max(0, rect.y())
        panel.move(x, y)
        panel.show()
        self._annotation_markers.append(panel)

    def _show_note_popup(self, anchor: QWidget, text: str) -> None:
        if self._note_preview_popup is None:
            return
        global_pos = anchor.mapToGlobal(QPoint(0, 0))
        self._note_preview_popup.show_note(global_pos, text)

    def _apply_extra_selections(self) -> None:
        self._text.setExtraSelections(self._annotation_extras + self._search_extras)

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

        pos_info = self._annotation_position_in_current_text(rec, self._visual_settings.reading_mode)
        if pos_info is None:
            return
        pos, length = pos_info
        doc_len = self._text.document().characterCount()
        if pos < 0 or pos >= doc_len:
            return
        end_pos = min(pos + max(length, 1), max(pos + 1, doc_len - 1))
        cursor = self._text.textCursor()
        cursor.setPosition(pos)
        cursor.setPosition(end_pos, QTextCursor.MoveMode.KeepAnchor)
        self._text.setTextCursor(cursor)
        self._text.ensureCursorVisible()


    def _toggle_search(self) -> None:
        if self._search_panel.isVisible():
            self._close_search_panel()
        else:
            self._search_panel.show()
            self._search_panel.raise_()
            self._reposition_search_panel()
            self._search_panel.input.setFocus()
            self._search_panel.input.selectAll()

    def _close_search_panel(self) -> None:
        self._search_panel.hide()
        self._search_matches = []
        self._search_idx = -1
        self._search_extras = []
        self._search_panel.set_counter(0, 0)
        self._search_panel.set_results([])
        self._apply_extra_selections()

    def _reposition_search_panel(self) -> None:
        if not hasattr(self, '_search_panel'): return
        w = self.width()
        x = w - self._search_panel.width() - 24
        self._search_panel.setGeometry(max(16, x), 50, 320, 500)

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

        self._search_matches = matches
        self._search_extras = extras
        self._search_idx = 0 if matches else -1
        self._search_panel.set_counter(1 if matches else 0, len(matches))
        self._apply_extra_selections()
        self._search_panel.set_results(matches)
        if matches:
            self._goto_match(matches[0][0], matches[0][1])

    def _goto_next_match(self) -> None:
        if not self._search_matches:
            return
        self._search_idx = (self._search_idx + 1) % len(self._search_matches)
        start, end, _ = self._search_matches[self._search_idx]
        self._search_panel.set_counter(self._search_idx + 1, len(self._search_matches))
        self._goto_match(start, end)

    def _goto_prev_match(self) -> None:
        if not self._search_matches:
            return
        self._search_idx = (self._search_idx - 1 + len(self._search_matches)) % len(self._search_matches)
        start, end, _ = self._search_matches[self._search_idx]
        self._search_panel.set_counter(self._search_idx + 1, len(self._search_matches))
        self._goto_match(start, end)

    def _goto_match(self, start: int, end: int) -> None:
        for idx, (s, e, _) in enumerate(self._search_matches):
            if s == start and e == end:
                self._search_idx = idx
                self._search_panel.set_counter(idx + 1, len(self._search_matches))
                break
        cursor = self._text.textCursor()
        doc_len = self._text.document().characterCount()
        s = max(0, min(start, max(0, doc_len - 1)))
        e = max(s + 1, min(end, max(1, doc_len - 1)))
        cursor.setPosition(s)
        cursor.setPosition(e, QTextCursor.MoveMode.KeepAnchor)
        self._text.setTextCursor(cursor)
        self._text.ensureCursorVisible()
