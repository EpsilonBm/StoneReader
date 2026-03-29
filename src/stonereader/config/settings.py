"""Local settings persistence helpers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(slots=True)
class AppSettings:
    theme: str = "day"
    font_family: str = "Microsoft YaHei UI"
    font_size: int = 18
    line_spacing: float = 1.5


def settings_dir() -> Path:
    root = Path.cwd() / ".local" / "settings"
    root.mkdir(parents=True, exist_ok=True)
    return root


def load_settings() -> AppSettings:
    path = settings_dir() / "app_settings.json"
    if not path.exists():
        return AppSettings()

    data = json.loads(path.read_text(encoding="utf-8"))
    return AppSettings(**data)


def save_settings(settings: AppSettings) -> None:
    path = settings_dir() / "app_settings.json"
    path.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
