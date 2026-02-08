# TMX_Editor

usage: tmx_editor.py [-h] [--merge] [--dedup] [--clean] [--strip-tags] [--csv] [--gui] [-o OUTPUT] [--strategy {skip,replace,keep_both}] [file]

TMX Editor - Analysis and Editing Tool for TMX Translation Memory Files

positional arguments:
  file                  TMX file to edit (or directory for --merge)

options:
  -h, --help            show this help message and exit
  -o, --output OUTPUT   Output file path (default: auto-generated)
  --strategy {skip,replace,keep_both}
                        Duplicate strategy for merge (default: skip)

batch operations:
  --merge               Merge all TMX files in a directory into one. Uses current directory if no path given.
  --dedup               Remove exact duplicates (non-interactive)
  --clean               Remove duplicates + empty/missing segments (non-interactive)
  --strip-tags          Strip inline formatting tags (non-interactive)
  --csv                 Export to CSV (non-interactive)
  --gui                 Launch retro TUI (Norton Commander / Turbo Pascal style)

Examples:
  tmx_editor.py                              Interactive mode
  tmx_editor.py file.tmx                     Interactive mode with file
  tmx_editor.py --gui file.tmx               Retro TUI (Norton Commander style)
  tmx_editor.py --merge                      Merge all TMX files in current directory
  tmx_editor.py --merge /path/to/tmx/files   Merge all TMX files in specified directory
  tmx_editor.py --merge --strategy replace   Merge, incoming overwrites existing
  tmx_editor.py --dedup file.tmx             Remove exact duplicates
  tmx_editor.py --clean file.tmx             Remove duplicates + empty segments
  tmx_editor.py --strip-tags file.tmx        Strip inline formatting tags
  tmx_editor.py --csv file.tmx               Export to CSV
  tmx_editor.py --dedup --strip-tags f.tmx   Chain multiple operations
  tmx_editor.py --dedup file.tmx -o out.tmx  Specify output file
