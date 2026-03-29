"""Utilities for screen-aware UI sizing."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtGui import QGuiApplication


@dataclass(slots=True)
class UiScale:
    width: int
    height: int
    card_w: int
    card_h: int
    cover_h: int
    spacing: int


def detect_ui_scale() -> UiScale:
    """Compute baseline UI values from primary screen size."""
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return UiScale(width=1280, height=800, card_w=170, card_h=260, cover_h=190, spacing=12)

    size = screen.availableGeometry().size()
    width = max(size.width(), 960)
    height = max(size.height(), 640)

    scale = min(width / 1440.0, height / 900.0)
    card_w = int(160 + 45 * scale)
    card_h = int(240 + 60 * scale)
    cover_h = int(card_h * 0.72)
    spacing = max(10, int(10 + 5 * scale))

    return UiScale(width=width, height=height, card_w=card_w, card_h=card_h, cover_h=cover_h, spacing=spacing)
