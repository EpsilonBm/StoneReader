# StoneReader

StoneReader is a lightweight and extensible e-book reader built with Python and PyQt6.

## Current Progress

- Preparation phase completed: project structure, dependency strategy, git-ready files.
- Iteration 1 completed: base framework, bookshelf UI, add-book import flow, and local bookshelf persistence.

## Quick Start

- Recommended Python version: 3.11 - 3.13 (PyQt6 is not stable on 3.14 in this setup).

1. Create and activate a virtual environment.
1. Install dependencies:

```bash
pip install -r requirements.txt
```

1. Run the GUI app from project root:

```bash
python run.py
```

1. Added books are persisted locally in `.local/library/books.json` and reloaded on next startup.

1. Optional: install in editable mode and use module/CLI entry.

```bash
pip install -e .
python -m stonereader
stonereader
```

## Project Structure

```text
src/stonereader/
  main.py
  app.py
  config/
  models/
  services/
  ui/
  utils/
docs/roadmap.md
```

## Iteration 1 Features

- Modular PyQt6 project skeleton.
- Bookshelf main window with:
  - left navigation and display options,
  - center area supporting grid/list modes,
  - add-book import flow.
- Basic responsive layout based on screen size.

## Tests

Run tests from project root:

```bash
pytest
```
