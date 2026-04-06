"""Convenience launcher for local development."""

from pathlib import Path
import os
import sys

src = Path(__file__).resolve().parent / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

from stonereader.main import run  # noqa: E402


if __name__ == "__main__":
    # Dev launcher: enable media diagnostics by default unless user explicitly disables it.
    os.environ.setdefault("STONEREADER_MEDIA_DEBUG", "1")
    raise SystemExit(run())
