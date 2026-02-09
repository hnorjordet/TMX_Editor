# TMX Editor

A Python tool for analyzing, cleaning, and manipulating TMX (Translation Memory eXchange) files. Built for translators and localization engineers who need to maintain and optimize their translation memories.

Includes a **retro terminal UI** inspired by Norton Commander and Turbo Pascal — blue background, white text, F-key menus, and all.

![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)

## Features

### Editing Operations
- **Remove exact duplicates** — Keeps the first occurrence, removes the rest (case-insensitive, whitespace-normalized)
- **Fuzzy duplicate detection** — Finds similar segments using `difflib.SequenceMatcher` with configurable threshold (default 85%)
- **Remove empty/missing segments** — Cleans up TUs with missing TUVs, empty source, or empty target
- **Strip inline formatting tags** — Removes `<bpt>`, `<ept>`, `<it>`, `<ph>`, `<hi>`, `<ut>` etc., keeping only the text content

### Export & Import
- **Filter and export** — Extract TUs by regex pattern (source/target), date range, or inverted criteria to a new TMX file
- **CSV export** — Export all TUs to CSV with UTF-8 BOM for Excel compatibility
- **Merge TMX files** — Combine multiple TMX files with configurable duplicate handling (`skip`, `replace`, or `keep_both`)

### Analysis (Companion Script)
- **Auto-translatable content detection** — Numbers, dates, URLs, emails, currency, measurements, version numbers, proper names
- **Duplicate analysis** — Exact duplicate identification with space savings calculation
- **Quality issues** — Missing/empty source or target segments

### Three Ways to Use It

| Mode | Command | Best for |
|------|---------|----------|
| **CLI batch** | `python3 tmx_editor.py --dedup file.tmx` | Automation, scripting |
| **Interactive menu** | `python3 tmx_editor.py file.tmx` | Quick manual operations |
| **Retro TUI** | `python3 tmx_editor.py --gui file.tmx` | Full visual editing |

## Requirements

- **Python 3.8+**
- **No external dependencies** — uses only the Python standard library (`xml.etree.ElementTree`, `difflib`, `curses`, `csv`, `argparse`)
- Works on **macOS**, **Linux**, and **Windows** (TUI requires a terminal with curses support; on Windows use Windows Terminal or WSL)

## Installation

```bash
git clone https://github.com/hnorjordet/TMX_Editor.git
cd TMX_Editor
```

That's it. No `pip install`, no virtual environment needed.

## Quick Start

```bash
# Remove duplicates from a TMX file
python3 tmx_editor.py --dedup my_memory.tmx

# Full cleanup: remove duplicates + empty segments
python3 tmx_editor.py --clean my_memory.tmx

# Launch the retro TUI
python3 tmx_editor.py --gui my_memory.tmx

# Merge all TMX files in a directory
python3 tmx_editor.py --merge /path/to/tmx/files/

# Run the analyzer for a detailed report
python3 tmx_analyzer.py my_memory.tmx
```

## Usage

### CLI Batch Mode

Run operations directly from the command line — ideal for scripting and automation.

```bash
# Remove exact duplicates
python3 tmx_editor.py --dedup file.tmx

# Remove duplicates + empty/missing segments
python3 tmx_editor.py --clean file.tmx

# Strip inline formatting tags
python3 tmx_editor.py --strip-tags file.tmx

# Export to CSV
python3 tmx_editor.py --csv file.tmx

# Chain multiple operations
python3 tmx_editor.py --dedup --strip-tags file.tmx

# Specify output file
python3 tmx_editor.py --dedup file.tmx -o cleaned_output.tmx

# Merge all TMX files in a directory
python3 tmx_editor.py --merge /path/to/tmx/files/

# Merge with incoming files overwriting existing translations
python3 tmx_editor.py --merge /path/to/tmx/files/ --strategy replace
```

### Interactive Menu Mode

```bash
python3 tmx_editor.py file.tmx
```

Presents a numbered menu where operations can be stacked before saving:

```
TMX Editor Menu:
  1. Remove exact duplicates
  2. Find fuzzy duplicates
  3. Remove empty/missing segments
  4. Strip inline formatting tags
  5. Filter and export TUs
  6. Export to CSV
  7. Merge another TMX file
  8. Show current statistics
  9. Save and exit
  0. Exit without saving
```

### Retro TUI Mode

```bash
python3 tmx_editor.py --gui file.tmx
```

A full-screen terminal interface in the style of Norton Commander / Turbo Pascal:

- **Blue background** with white text
- **Table view** of all TUs with source, target, and status columns
- **Color-coded markers**: `DUP` (red) for duplicates, `EMPTY` (red) for missing segments, `TAG` (yellow) for tagged segments
- **Dropdown menus** with keyboard navigation
- **Dialog boxes** with double-line borders
- **F-key shortcuts** displayed at the bottom

#### TUI Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `↑` `↓` | Navigate rows |
| `PgUp` `PgDn` | Scroll pages |
| `Home` `End` | Jump to start/end |
| `F1` / `ESC` | Open menu bar |
| `F2` | Save |
| `F3` | Open file |
| `F5` | Export CSV |
| `F6` | Remove duplicates |
| `F7` | Fuzzy duplicates |
| `F8` | Remove empty segments |
| `F9` | Statistics |
| `F10` / `Q` | Quit |
| `A` | Filter: Show all |
| `D` | Filter: Duplicates only |
| `E` | Filter: Empty only |
| `T` | Filter: Tagged only |

### TMX Analyzer

The companion analysis script generates a detailed text report:

```bash
python3 tmx_analyzer.py my_memory.tmx
```

Output includes:
- Auto-translatable content breakdown by category
- Exact duplicate listing with occurrence counts and space savings estimate
- Missing/empty segment inventory
- Detailed examples for each finding

## Merge Strategies

When merging TMX files, you can control how duplicates are handled:

| Strategy | Flag | Behavior |
|----------|------|----------|
| **Skip** (default) | `--strategy skip` | Keep existing translation, ignore incoming |
| **Replace** | `--strategy replace` | Incoming translation overwrites existing |
| **Keep both** | `--strategy keep_both` | Both versions are kept in the merged file |

**Batch merge example** — put all your TMX files in one directory:

```bash
python3 tmx_editor.py --merge /path/to/tmx/files/
```

This finds all `.tmx` files in the directory, uses the first one (alphabetically) as the base, and merges the rest in. Exact duplicates (same source + same target) are always skipped regardless of strategy.

## How It Works

### TMX Preservation

The editor preserves the original TMX structure when writing:

- **DOCTYPE declaration** is captured from the raw file and re-injected (ElementTree discards it)
- **`xml:lang` attributes** serialize correctly via namespace registration
- **Encoding** is detected from the XML declaration and preserved
- **Original file is never overwritten** — output files get a suffix and timestamp (e.g., `memory_deduped_20260209_143022.tmx`)

### Duplicate Detection

**Exact duplicates**: Source and target text are normalized (lowercased, whitespace collapsed) and compared as a combined key. First occurrence is kept.

**Fuzzy duplicates**: Uses Python's `difflib.SequenceMatcher` with a length-ratio pruning optimization — segments whose length ratio makes it impossible to reach the threshold are skipped, dramatically reducing comparisons for large files.

### File Size

Typical translation memories range from a few thousand to several hundred thousand TUs. The editor loads the full file into memory using ElementTree, which works well for files up to ~1 GB. For the fuzzy duplicate operation, a warning is displayed when there are more than 50,000 unique segments.

## File Structure

```
TMX_Editor/
├── tmx_editor.py      # Main script — CLI, batch operations, interactive menu
├── tmx_tui.py         # Retro TUI (Norton Commander style)
├── tmx_analyzer.py    # Analysis-only script (detailed reports)
├── README.md
└── .gitignore
```

## License

MIT License. See [LICENSE](LICENSE) for details.

## Acknowledgments

- Inspired by [Heartsome TMX Editor 8](https://github.com/heartsome/tmxeditor8), a Java-based TMX editor
- The retro TUI is a tribute to Norton Commander, Turbo Pascal, and the golden age of DOS computing
- Built with the Python standard library — no dependencies, no fuss
