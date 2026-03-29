# Roadmap

## Iteration 1

### Design

- Build a modular PyQt6 architecture with clear separation of UI, models, and services.
- Main UI is a bookshelf view with left-side filters and center dual-mode book display.
- Screen-aware layout should adapt card size and spacing for different displays.

### Development

- Project skeleton and startup pipeline established.
- Bookshelf main window created with:
  - navigation tree: Shelf, Tags, Favorites, Read,
  - sort controls (reading time, added time, title, author),
  - grid/list toggle button,
  - add-book button connected to file import flow,
  - add-book placeholder card in shelf view,
  - shelf list persisted locally and restored on next startup.
- UI polish pass:
  - fixed text/background contrast,
  - improved button style,
  - fixed responsive card layout when splitter width changes.
- App entry provided:
  - `python run.py`
  - `python -m stonereader` (after `pip install -e .`)
  - `stonereader` (CLI script after `pip install -e .`)

### Testing

- Added unit tests for sorting, dedup import, and persistence reload behavior.

### Review Notes

- Iteration 1 deliverables completed and pending user review.
- Next step after review: reading view and text rendering in Iteration 2.
