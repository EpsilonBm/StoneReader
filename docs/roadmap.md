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
  - grid/list switch,
  - add-book button and placeholder card.

### Testing

- Added unit test for in-memory book sorting and filtering behavior.

### Review Notes

- Pending user review for UI style and interaction details.
- Next step after review: file import and persistence integration.
