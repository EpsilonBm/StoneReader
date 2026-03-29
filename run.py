"""Convenience launcher for local development."""

from pathlib import Path
import sys

src = Path(__file__).resolve().parent / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

from stonereader.main import run  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(run())
