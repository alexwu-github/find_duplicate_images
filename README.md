# Duplicate Image Finder

A desktop app for finding duplicate photos across drives and folders. It compares files by
content, not filename, so renamed or moved copies are still caught — and it never deletes or
modifies anything; it only lists what it finds.

## Features

- **Scan multiple drives/folders at once** — add as many locations as you like to a single scan.
- **Content-based matching** — files are grouped by size first, then by an MD5 hash of their
  contents, so two images only get flagged as duplicates if their bytes actually match.
- **80+ supported formats** — standard formats (JPG, PNG, GIF, TIFF, WebP, …) plus RAW formats
  from Canon, Nikon, Sony, Fuji, Olympus, Panasonic, Pentax, Leica, Hasselblad, Sigma, Phase One,
  Samsung, Kodak, Minolta, Epson, Mamiya, and more, with per-format checkboxes and quick-select
  buttons (Standard / RAW only / all / none).
- **Cancel-safe** — stopping a scan early still shows every duplicate group confirmed so far,
  instead of discarding the work.
- **Export results** — save the results as a plain-text report or as CSV.
- **Read-only** — the app only reports duplicates; it has no delete or file-modification feature.
  Removing files is left to you, using whatever file manager you trust.

## Requirements

- Python 3.14 or 3.15
- [Poetry](https://python-poetry.org/) for dependency management

## Installation

```bash
poetry install
```

## Usage

```bash
poetry run python -m find_duplicate_images.main
```

1. **Add Drive/Folder** for each location you want to scan.
2. Pick which file formats to include, or use a quick-select button (Select All, Select
   Standard, Select RAW Only, Deselect All).
3. **Start Scan**. Progress and the current file are shown live; **Stop Scan** cancels early
   while keeping whatever duplicate groups were already confirmed.
4. Review the results, grouped by duplicate set with each file's name, folder, and size.
5. **Export Results** to a `.txt` report or a `.csv` file if you want to keep or process the list.

## Building a standalone Windows executable

A GitHub Actions workflow (`.github/workflows/build.yml`) builds a Windows `.exe` with
PyInstaller. Trigger it manually from the **Actions** tab (`Build EXE` → **Run workflow**); the
resulting executable is uploaded as a build artifact.

To build locally on Windows instead:

```bash
poetry run pyinstaller --onefile --windowed src/find_duplicate_images/main.py
```

## Project structure

```
src/find_duplicate_images/
├── main.py     # entry point
├── gui.py      # Tkinter UI
├── scanner.py  # duplicate-detection logic
└── config.py   # supported file extensions
```
