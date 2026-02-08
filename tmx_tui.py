"""
TMX Editor - Retro Terminal User Interface

Norton Commander / Turbo Pascal inspired TUI for TMX editing.
Blue background, white text, F-key menus, table view.

Launched via: python3 tmx_editor.py --gui [file.tmx]
"""

import curses
import curses.textpad
import os
import sys
from pathlib import Path
from typing import Optional, List, Tuple

from tmx_editor import TMXEditor


# ══════════════════════════════════════════════════
# Color scheme constants
# ══════════════════════════════════════════════════

# Color pair IDs
CP_NORMAL = 1       # White on blue (main area)
CP_HEADER = 2       # White on cyan (title bar)
CP_MENU_BAR = 3     # Black on cyan (menu bar)
CP_MENU_KEY = 4     # Yellow on cyan (F-key highlight in menu bar)
CP_STATUS = 5       # Black on cyan (status bar)
CP_TABLE_HDR = 6    # Yellow on blue (table column headers)
CP_SELECTED = 7     # Black on white (selected row)
CP_DUP = 8          # Red on blue (duplicate marker)
CP_EMPTY = 9        # Red on blue (empty/error marker)
CP_DIALOG = 10      # Black on white (dialog box)
CP_DIALOG_BTN = 11  # White on cyan (dialog button)
CP_DIALOG_TITLE = 12  # Yellow on white (dialog title)
CP_MENU_DROP = 13   # Black on white (dropdown menu)
CP_MENU_SEL = 14    # White on blue (dropdown menu selected)
CP_MODIFIED = 15    # Yellow on blue (modified indicator)


def _init_colors():
    """Initialize the retro color scheme."""
    curses.start_color()
    curses.use_default_colors()

    curses.init_pair(CP_NORMAL, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(CP_HEADER, curses.COLOR_WHITE, curses.COLOR_CYAN)
    curses.init_pair(CP_MENU_BAR, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(CP_MENU_KEY, curses.COLOR_YELLOW, curses.COLOR_CYAN)
    curses.init_pair(CP_STATUS, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(CP_TABLE_HDR, curses.COLOR_YELLOW, curses.COLOR_BLUE)
    curses.init_pair(CP_SELECTED, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(CP_DUP, curses.COLOR_RED, curses.COLOR_BLUE)
    curses.init_pair(CP_EMPTY, curses.COLOR_RED, curses.COLOR_BLUE)
    curses.init_pair(CP_DIALOG, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(CP_DIALOG_BTN, curses.COLOR_WHITE, curses.COLOR_CYAN)
    curses.init_pair(CP_DIALOG_TITLE, curses.COLOR_YELLOW, curses.COLOR_WHITE)
    curses.init_pair(CP_MENU_DROP, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(CP_MENU_SEL, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(CP_MODIFIED, curses.COLOR_YELLOW, curses.COLOR_BLUE)


# ══════════════════════════════════════════════════
# TU data cache for display
# ══════════════════════════════════════════════════

class TURow:
    """A single TU row for display in the table."""
    __slots__ = ('index', 'source', 'target', 'status', 'creation_date')

    def __init__(self, index: int, source: str, target: str,
                 status: str = '', creation_date: str = ''):
        self.index = index
        self.source = source
        self.target = target
        self.status = status  # '', 'DUP', 'EMPTY', 'TAG'
        self.creation_date = creation_date


# ══════════════════════════════════════════════════
# Main TUI Application
# ══════════════════════════════════════════════════

class TMXTui:
    """Norton Commander / Turbo Pascal style TUI for TMX editing."""

    MENU_ITEMS = {
        'File': [
            ('Open...', 'F3'),
            ('Save', 'F2'),
            ('Save As...', 'Shift+F2'),
            ('Export CSV...', 'F5'),
            ('─', ''),
            ('Quit', 'F10'),
        ],
        'Edit': [
            ('Remove Exact Duplicates', 'F6'),
            ('Find Fuzzy Duplicates...', 'F7'),
            ('Remove Empty Segments', 'F8'),
            ('Strip Inline Tags', 'Ctrl+T'),
        ],
        'Filter': [
            ('Show All', 'A'),
            ('Show Duplicates Only', 'D'),
            ('Show Empty Only', 'E'),
            ('Show Tagged Only', 'T'),
        ],
        'Tools': [
            ('Merge TMX File...', 'Ctrl+M'),
            ('Statistics', 'F9'),
        ],
    }

    def __init__(self, stdscr, file_path: str = None):
        self.stdscr = stdscr
        self.editor = TMXEditor()
        self.rows: List[TURow] = []
        self.filtered_rows: List[TURow] = []
        self.scroll_offset = 0
        self.selected_row = 0
        self.modifications_made = False
        self.current_filter = 'all'
        self.status_message = ''
        self.active_menu = None  # None or menu name
        self.active_menu_item = 0
        self.file_path = file_path

        # Screen dimensions
        self.height = 0
        self.width = 0

    def run(self):
        """Main entry point for the TUI."""
        self._setup_screen()

        if self.file_path:
            self._load_file(self.file_path)
        else:
            path = self._file_dialog("Open TMX File")
            if path:
                self._load_file(path)
            else:
                return

        self._main_loop()

    def _setup_screen(self):
        """Configure curses settings."""
        _init_colors()
        curses.curs_set(0)  # Hide cursor
        self.stdscr.keypad(True)
        self.stdscr.timeout(-1)  # Blocking input
        self.height, self.width = self.stdscr.getmaxyx()

    def _load_file(self, path: str):
        """Load a TMX file and build the display rows."""
        try:
            # Suppress print output from editor.load()
            old_stdout = sys.stdout
            sys.stdout = open(os.devnull, 'w')
            try:
                self.editor.load(path)
            finally:
                sys.stdout.close()
                sys.stdout = old_stdout

            self.file_path = path
            self._rebuild_rows()
            self.status_message = f"Loaded {Path(path).name} ({len(self.rows):,} TUs)"
        except Exception as e:
            self.status_message = f"Error: {e}"

    def _rebuild_rows(self):
        """Rebuild display rows from the editor's TMX tree."""
        self.rows = []
        body = self.editor._get_body()

        # Build duplicate lookup
        seen = {}
        dup_keys = set()
        all_tus = list(body.findall('tu'))

        for i, tu in enumerate(all_tus):
            src, tgt = self.editor._get_tu_texts(tu)
            if src is not None:
                key = f"{' '.join(src.lower().split())}|||{' '.join((tgt or '').lower().split())}"
                if key in seen:
                    dup_keys.add(key)
                else:
                    seen[key] = i

        # Build rows
        for i, tu in enumerate(all_tus):
            src, tgt = self.editor._get_tu_texts(tu)

            if src is None:
                src = ""
            if tgt is None:
                tgt = ""

            # Determine status
            status = ''
            if not src or not tgt:
                status = 'EMPTY'
            else:
                key = f"{' '.join(src.lower().split())}|||{' '.join((tgt or '').lower().split())}"
                if key in dup_keys:
                    status = 'DUP'

            # Check for inline tags
            has_tags = False
            for seg in tu.iter('seg'):
                if list(seg):
                    has_tags = True
                    break
            if has_tags and not status:
                status = 'TAG'

            creation_date = tu.get('creationdate', '')

            self.rows.append(TURow(i + 1, src, tgt, status, creation_date))

        self._apply_filter()

    def _apply_filter(self):
        """Apply the current filter to rows."""
        if self.current_filter == 'all':
            self.filtered_rows = self.rows[:]
        elif self.current_filter == 'dup':
            self.filtered_rows = [r for r in self.rows if r.status == 'DUP']
        elif self.current_filter == 'empty':
            self.filtered_rows = [r for r in self.rows if r.status == 'EMPTY']
        elif self.current_filter == 'tagged':
            self.filtered_rows = [r for r in self.rows if r.status == 'TAG']

        self.selected_row = 0
        self.scroll_offset = 0

    # ──────────────────────────────────────────────
    # Drawing
    # ──────────────────────────────────────────────

    def _draw(self):
        """Redraw the entire screen."""
        self.height, self.width = self.stdscr.getmaxyx()
        self.stdscr.bkgd(' ', curses.color_pair(CP_NORMAL))
        self.stdscr.erase()

        self._draw_title_bar()
        self._draw_menu_bar()
        self._draw_table_header()
        self._draw_table_body()
        self._draw_status_bar()
        self._draw_fkey_bar()

        if self.active_menu:
            self._draw_dropdown_menu()

        self.stdscr.noutrefresh()
        curses.doupdate()

    def _draw_title_bar(self):
        """Draw the top title bar."""
        title = " TMX Editor "
        file_info = ""
        if self.file_path:
            mod = " [Modified]" if self.modifications_made else ""
            file_info = f" - {Path(self.file_path).name}{mod}"
            lang_info = f" ({self.editor.source_lang} -> {self.editor.target_lang})"
            file_info += lang_info

        full_title = title + file_info
        bar = full_title.ljust(self.width)[:self.width]

        try:
            self.stdscr.addstr(0, 0, bar, curses.color_pair(CP_HEADER) | curses.A_BOLD)
            if self.modifications_made and file_info:
                # Highlight [Modified] in yellow
                mod_pos = bar.find('[Modified]')
                if mod_pos >= 0:
                    self.stdscr.addstr(0, mod_pos, '[Modified]',
                                       curses.color_pair(CP_MENU_KEY) | curses.A_BOLD)
        except curses.error:
            pass

    def _draw_menu_bar(self):
        """Draw the menu bar (row 1)."""
        bar = " ".ljust(self.width)
        try:
            self.stdscr.addstr(1, 0, bar[:self.width], curses.color_pair(CP_MENU_BAR))
        except curses.error:
            pass

        x = 1
        for menu_name in self.MENU_ITEMS:
            label = f" {menu_name} "
            if self.active_menu == menu_name:
                attr = curses.color_pair(CP_MENU_SEL) | curses.A_BOLD
            else:
                attr = curses.color_pair(CP_MENU_BAR)

            try:
                self.stdscr.addstr(1, x, label, attr)
                # Highlight first letter
                self.stdscr.addstr(1, x + 1, menu_name[0],
                                   attr | curses.A_UNDERLINE)
            except curses.error:
                pass
            x += len(label) + 1

    def _draw_table_header(self):
        """Draw the table column headers."""
        y = 2
        w = self.width

        # Column widths
        num_w = 7
        status_w = 5
        # Split remaining space between source and target
        remaining = w - num_w - status_w - 3  # 3 for separators
        src_w = remaining // 2
        tgt_w = remaining - src_w

        hdr = (f"{'#':>{num_w}}"
               f"{'':1}"
               f"{'Source':<{src_w}}"
               f"{'':1}"
               f"{'Target':<{tgt_w}}"
               f"{'':1}"
               f"{'St':<{status_w}}")

        try:
            self.stdscr.addstr(y, 0, hdr[:w], curses.color_pair(CP_TABLE_HDR) | curses.A_BOLD)
            # Separator line
            sep = "─" * w
            self.stdscr.addstr(y + 1, 0, sep[:w], curses.color_pair(CP_TABLE_HDR))
        except curses.error:
            pass

    def _draw_table_body(self):
        """Draw the TU rows in the table area."""
        start_y = 4  # After title, menu, header, separator
        end_y = self.height - 2  # Leave room for status + fkey bar
        visible_rows = end_y - start_y
        w = self.width

        # Column widths (must match header)
        num_w = 7
        status_w = 5
        remaining = w - num_w - status_w - 3
        src_w = remaining // 2
        tgt_w = remaining - src_w

        # Ensure selected row is visible
        if self.selected_row < self.scroll_offset:
            self.scroll_offset = self.selected_row
        elif self.selected_row >= self.scroll_offset + visible_rows:
            self.scroll_offset = self.selected_row - visible_rows + 1

        for screen_row in range(visible_rows):
            data_idx = self.scroll_offset + screen_row
            y = start_y + screen_row

            if data_idx >= len(self.filtered_rows):
                # Empty row
                try:
                    self.stdscr.addstr(y, 0, " " * w, curses.color_pair(CP_NORMAL))
                except curses.error:
                    pass
                continue

            row = self.filtered_rows[data_idx]
            is_selected = (data_idx == self.selected_row)

            # Truncate text to column width
            src_text = row.source[:src_w - 1].replace('\n', ' ')
            tgt_text = row.target[:tgt_w - 1].replace('\n', ' ')

            line = (f"{row.index:>{num_w}}"
                    f"{'':1}"
                    f"{src_text:<{src_w}}"
                    f"{'':1}"
                    f"{tgt_text:<{tgt_w}}"
                    f"{'':1}"
                    f"{row.status:<{status_w}}")

            line = line[:w]

            if is_selected:
                attr = curses.color_pair(CP_SELECTED)
            else:
                attr = curses.color_pair(CP_NORMAL)

            try:
                self.stdscr.addstr(y, 0, line, attr)

                # Color the status marker
                if row.status and not is_selected:
                    status_x = num_w + 1 + src_w + 1 + tgt_w + 1
                    if row.status == 'DUP':
                        self.stdscr.addstr(y, status_x, row.status,
                                           curses.color_pair(CP_DUP) | curses.A_BOLD)
                    elif row.status == 'EMPTY':
                        self.stdscr.addstr(y, min(status_x, w - 6), row.status[:4],
                                           curses.color_pair(CP_EMPTY) | curses.A_BOLD)
                    elif row.status == 'TAG':
                        self.stdscr.addstr(y, status_x, row.status,
                                           curses.color_pair(CP_MODIFIED) | curses.A_BOLD)
            except curses.error:
                pass

    def _draw_status_bar(self):
        """Draw the status bar (second from bottom)."""
        y = self.height - 2
        w = self.width

        # Left side: status message
        left = f" {self.status_message}"

        # Right side: row info and filter
        filter_labels = {'all': 'All', 'dup': 'Duplicates', 'empty': 'Empty', 'tagged': 'Tagged'}
        right = (f"Row {self.selected_row + 1}/{len(self.filtered_rows)} "
                 f"| Filter: {filter_labels.get(self.current_filter, 'All')} "
                 f"| Total: {len(self.rows):,} ")

        padding = w - len(left) - len(right)
        if padding < 0:
            padding = 0
        bar = (left + " " * padding + right)[:w]

        try:
            self.stdscr.addstr(y, 0, bar, curses.color_pair(CP_STATUS))
        except curses.error:
            pass

    def _draw_fkey_bar(self):
        """Draw the F-key shortcut bar at the bottom."""
        y = self.height - 1
        w = self.width

        keys = [
            ('F2', 'Save'),
            ('F3', 'Open'),
            ('F5', 'CSV'),
            ('F6', 'Dedup'),
            ('F7', 'Fuzzy'),
            ('F8', 'Empty'),
            ('F9', 'Stats'),
            ('F10', 'Quit'),
        ]

        x = 0
        for key_name, label in keys:
            if x >= w - 1:
                break
            try:
                # F-key number in black on cyan
                self.stdscr.addstr(y, x, key_name,
                                   curses.color_pair(CP_MENU_KEY) | curses.A_BOLD)
                x += len(key_name)
                # Label in black on cyan
                disp = label[:8]
                self.stdscr.addstr(y, x, disp, curses.color_pair(CP_MENU_BAR))
                x += len(disp)
                # Small gap
                if x < w:
                    self.stdscr.addstr(y, x, " ", curses.color_pair(CP_MENU_BAR))
                    x += 1
            except curses.error:
                pass

        # Fill rest of line
        if x < w:
            try:
                self.stdscr.addstr(y, x, " " * (w - x), curses.color_pair(CP_MENU_BAR))
            except curses.error:
                pass

    def _draw_dropdown_menu(self):
        """Draw a dropdown menu from the menu bar."""
        if not self.active_menu or self.active_menu not in self.MENU_ITEMS:
            return

        items = self.MENU_ITEMS[self.active_menu]

        # Calculate menu position
        x = 1
        for name in self.MENU_ITEMS:
            if name == self.active_menu:
                break
            x += len(name) + 3

        # Menu dimensions
        menu_w = max(len(item[0]) + len(item[1]) + 4 for item in items) + 2
        menu_h = len(items) + 2
        menu_y = 2

        # Draw menu box
        try:
            # Top border
            self.stdscr.addstr(menu_y, x, "┌" + "─" * (menu_w - 2) + "┐",
                               curses.color_pair(CP_MENU_DROP))

            for i, (label, shortcut) in enumerate(items):
                row_y = menu_y + 1 + i

                if label == '─':
                    # Separator
                    self.stdscr.addstr(row_y, x, "├" + "─" * (menu_w - 2) + "┤",
                                       curses.color_pair(CP_MENU_DROP))
                else:
                    is_sel = (i == self.active_menu_item)
                    attr = curses.color_pair(CP_MENU_SEL if is_sel else CP_MENU_DROP)

                    inner_w = menu_w - 2
                    sc_w = len(shortcut)
                    label_w = inner_w - sc_w - 1
                    content = f" {label:<{label_w}}{shortcut:>{sc_w}} "

                    self.stdscr.addstr(row_y, x, "│", curses.color_pair(CP_MENU_DROP))
                    self.stdscr.addstr(row_y, x + 1, content[:inner_w], attr)
                    self.stdscr.addstr(row_y, x + menu_w - 1, "│",
                                       curses.color_pair(CP_MENU_DROP))

            # Bottom border
            self.stdscr.addstr(menu_y + menu_h - 1, x,
                               "└" + "─" * (menu_w - 2) + "┘",
                               curses.color_pair(CP_MENU_DROP))
        except curses.error:
            pass

    # ──────────────────────────────────────────────
    # Dialogs
    # ──────────────────────────────────────────────

    def _message_dialog(self, title: str, message: str, wait: bool = True):
        """Show a message dialog box."""
        lines = message.split('\n')
        box_w = max(max(len(l) for l in lines) + 4, len(title) + 6, 30)
        box_h = len(lines) + 4
        y = (self.height - box_h) // 2
        x = (self.width - box_w) // 2

        try:
            # Draw box with shadow
            for row in range(box_h):
                self.stdscr.addstr(y + row, x, " " * box_w,
                                   curses.color_pair(CP_DIALOG))

            # Border
            self.stdscr.addstr(y, x, "╔" + "═" * (box_w - 2) + "╗",
                               curses.color_pair(CP_DIALOG))
            for row in range(1, box_h - 1):
                self.stdscr.addstr(y + row, x, "║", curses.color_pair(CP_DIALOG))
                self.stdscr.addstr(y + row, x + box_w - 1, "║",
                                   curses.color_pair(CP_DIALOG))
            self.stdscr.addstr(y + box_h - 1, x, "╚" + "═" * (box_w - 2) + "╝",
                               curses.color_pair(CP_DIALOG))

            # Title
            title_str = f" {title} "
            title_x = x + (box_w - len(title_str)) // 2
            self.stdscr.addstr(y, title_x, title_str,
                               curses.color_pair(CP_DIALOG_TITLE) | curses.A_BOLD)

            # Message lines
            for i, line in enumerate(lines):
                self.stdscr.addstr(y + 1 + i, x + 2, line[:box_w - 4],
                                   curses.color_pair(CP_DIALOG))

            if wait:
                # OK button
                btn = " OK "
                btn_x = x + (box_w - len(btn)) // 2
                btn_y = y + box_h - 2
                self.stdscr.addstr(btn_y, btn_x, btn,
                                   curses.color_pair(CP_DIALOG_BTN) | curses.A_BOLD)

                self.stdscr.refresh()
                self.stdscr.getch()
        except curses.error:
            pass

    def _confirm_dialog(self, title: str, message: str) -> bool:
        """Show a Yes/No confirmation dialog."""
        lines = message.split('\n')
        box_w = max(max(len(l) for l in lines) + 4, len(title) + 6, 30)
        box_h = len(lines) + 5
        y = (self.height - box_h) // 2
        x = (self.width - box_w) // 2
        selected = 0  # 0 = Yes, 1 = No

        while True:
            try:
                # Draw box
                for row in range(box_h):
                    self.stdscr.addstr(y + row, x, " " * box_w,
                                       curses.color_pair(CP_DIALOG))

                # Border
                self.stdscr.addstr(y, x, "╔" + "═" * (box_w - 2) + "╗",
                                   curses.color_pair(CP_DIALOG))
                for row in range(1, box_h - 1):
                    self.stdscr.addstr(y + row, x, "║", curses.color_pair(CP_DIALOG))
                    self.stdscr.addstr(y + row, x + box_w - 1, "║",
                                       curses.color_pair(CP_DIALOG))
                self.stdscr.addstr(y + box_h - 1, x,
                                   "╚" + "═" * (box_w - 2) + "╝",
                                   curses.color_pair(CP_DIALOG))

                # Title
                title_str = f" {title} "
                title_x = x + (box_w - len(title_str)) // 2
                self.stdscr.addstr(y, title_x, title_str,
                                   curses.color_pair(CP_DIALOG_TITLE) | curses.A_BOLD)

                # Message
                for i, line in enumerate(lines):
                    self.stdscr.addstr(y + 1 + i, x + 2, line[:box_w - 4],
                                       curses.color_pair(CP_DIALOG))

                # Buttons
                btn_y = y + box_h - 2
                yes_btn = " Yes "
                no_btn = " No "
                gap = 4
                total_btn_w = len(yes_btn) + len(no_btn) + gap
                btn_start = x + (box_w - total_btn_w) // 2

                yes_attr = curses.color_pair(CP_DIALOG_BTN if selected == 0 else CP_DIALOG) | curses.A_BOLD
                no_attr = curses.color_pair(CP_DIALOG_BTN if selected == 1 else CP_DIALOG) | curses.A_BOLD

                self.stdscr.addstr(btn_y, btn_start, yes_btn, yes_attr)
                self.stdscr.addstr(btn_y, btn_start + len(yes_btn) + gap, no_btn, no_attr)

                self.stdscr.refresh()
            except curses.error:
                pass

            key = self.stdscr.getch()
            if key in (curses.KEY_LEFT, curses.KEY_RIGHT, ord('\t')):
                selected = 1 - selected
            elif key in (ord('\n'), ord('\r')):
                return selected == 0
            elif key == ord('y') or key == ord('Y') or key == ord('j') or key == ord('J'):
                return True
            elif key == ord('n') or key == ord('N') or key == 27:  # ESC
                return False

    def _file_dialog(self, title: str) -> Optional[str]:
        """Simple file path input dialog."""
        box_w = min(self.width - 4, 70)
        box_h = 5
        y = (self.height - box_h) // 2
        x = (self.width - box_w) // 2

        try:
            # Draw box
            for row in range(box_h):
                self.stdscr.addstr(y + row, x, " " * box_w,
                                   curses.color_pair(CP_DIALOG))

            self.stdscr.addstr(y, x, "╔" + "═" * (box_w - 2) + "╗",
                               curses.color_pair(CP_DIALOG))
            for row in range(1, box_h - 1):
                self.stdscr.addstr(y + row, x, "║", curses.color_pair(CP_DIALOG))
                self.stdscr.addstr(y + row, x + box_w - 1, "║",
                                   curses.color_pair(CP_DIALOG))
            self.stdscr.addstr(y + box_h - 1, x,
                               "╚" + "═" * (box_w - 2) + "╝",
                               curses.color_pair(CP_DIALOG))

            title_str = f" {title} "
            title_x = x + (box_w - len(title_str)) // 2
            self.stdscr.addstr(y, title_x, title_str,
                               curses.color_pair(CP_DIALOG_TITLE) | curses.A_BOLD)

            self.stdscr.addstr(y + 1, x + 2, "Path:",
                               curses.color_pair(CP_DIALOG))

            # Input field
            field_y = y + 2
            field_x = x + 2
            field_w = box_w - 4

            self.stdscr.addstr(field_y, field_x, " " * field_w,
                               curses.color_pair(CP_DIALOG) | curses.A_UNDERLINE)

            self.stdscr.refresh()
            curses.curs_set(1)
            curses.echo()

            # Read input
            self.stdscr.move(field_y, field_x)
            input_bytes = self.stdscr.getstr(field_y, field_x, field_w)
            path = input_bytes.decode('utf-8').strip().strip('"').strip("'")

            curses.noecho()
            curses.curs_set(0)

            return path if path else None
        except curses.error:
            curses.noecho()
            curses.curs_set(0)
            return None

    def _input_dialog(self, title: str, prompt: str, default: str = '') -> Optional[str]:
        """Simple text input dialog."""
        box_w = min(self.width - 4, 60)
        box_h = 5
        y = (self.height - box_h) // 2
        x = (self.width - box_w) // 2

        try:
            for row in range(box_h):
                self.stdscr.addstr(y + row, x, " " * box_w,
                                   curses.color_pair(CP_DIALOG))

            self.stdscr.addstr(y, x, "╔" + "═" * (box_w - 2) + "╗",
                               curses.color_pair(CP_DIALOG))
            for row in range(1, box_h - 1):
                self.stdscr.addstr(y + row, x, "║", curses.color_pair(CP_DIALOG))
                self.stdscr.addstr(y + row, x + box_w - 1, "║",
                                   curses.color_pair(CP_DIALOG))
            self.stdscr.addstr(y + box_h - 1, x,
                               "╚" + "═" * (box_w - 2) + "╝",
                               curses.color_pair(CP_DIALOG))

            title_str = f" {title} "
            title_x = x + (box_w - len(title_str)) // 2
            self.stdscr.addstr(y, title_x, title_str,
                               curses.color_pair(CP_DIALOG_TITLE) | curses.A_BOLD)

            self.stdscr.addstr(y + 1, x + 2, prompt[:box_w - 4],
                               curses.color_pair(CP_DIALOG))

            field_y = y + 2
            field_x = x + 2
            field_w = box_w - 4

            self.stdscr.addstr(field_y, field_x, default.ljust(field_w)[:field_w],
                               curses.color_pair(CP_DIALOG) | curses.A_UNDERLINE)

            self.stdscr.refresh()
            curses.curs_set(1)
            curses.echo()

            self.stdscr.move(field_y, field_x)
            input_bytes = self.stdscr.getstr(field_y, field_x, field_w)
            result = input_bytes.decode('utf-8').strip()

            curses.noecho()
            curses.curs_set(0)

            return result if result else default if default else None
        except curses.error:
            curses.noecho()
            curses.curs_set(0)
            return None

    # ──────────────────────────────────────────────
    # Operations
    # ──────────────────────────────────────────────

    def _op_save(self):
        """Save the TMX file."""
        if not self.modifications_made:
            self.status_message = "No modifications to save."
            return

        output = self.editor._generate_output_path('_edited')
        result = self._input_dialog("Save As", "Output file:", output)
        if result:
            try:
                self.editor.save(result)
                self.status_message = f"Saved to: {Path(result).name}"
                self.modifications_made = False
            except Exception as e:
                self.status_message = f"Save error: {e}"

    def _op_dedup(self):
        """Remove exact duplicates."""
        result = self.editor.remove_exact_duplicates()
        if result['removed_count'] > 0:
            self.modifications_made = True
            self._rebuild_rows()
            self.status_message = (f"Removed {result['removed_count']:,} duplicates "
                                   f"({result['total_before']:,} -> {result['unique_count']:,})")
        else:
            self.status_message = "No exact duplicates found."

    def _op_fuzzy(self):
        """Find and remove fuzzy duplicates."""
        threshold_str = self._input_dialog("Fuzzy Duplicates",
                                           "Similarity threshold (0-100):", "85")
        if not threshold_str:
            return

        try:
            threshold = float(threshold_str) / 100.0
            if not 0 < threshold <= 1:
                threshold = 0.85
        except ValueError:
            threshold = 0.85

        self.status_message = f"Searching fuzzy duplicates ({threshold*100:.0f}%)..."
        self._draw()

        groups = self.editor.find_fuzzy_duplicates(threshold=threshold)

        if not groups:
            self.status_message = "No fuzzy duplicates found."
            return

        total = sum(len(g['similar_tus']) for g in groups)
        msg = f"Found {len(groups)} groups with {total} fuzzy duplicates.\n\nRemove them?"

        if self._confirm_dialog("Fuzzy Duplicates", msg):
            result = self.editor.remove_fuzzy_duplicates(groups)
            self.modifications_made = True
            self._rebuild_rows()
            self.status_message = f"Removed {result['removed_count']:,} fuzzy duplicates."
        else:
            self.status_message = f"Found {total} fuzzy duplicates (not removed)."

    def _op_remove_empty(self):
        """Remove empty/missing segments."""
        result = self.editor.remove_empty_segments()
        if result['removed_count'] > 0:
            self.modifications_made = True
            self._rebuild_rows()
            self.status_message = (f"Removed {result['removed_count']:,} empty segments "
                                   f"({result['total_before']:,} -> {result['remaining_count']:,})")
        else:
            self.status_message = "No empty segments found."

    def _op_strip_tags(self):
        """Strip inline formatting tags."""
        result = self.editor.strip_inline_tags()
        if result['segments_modified'] > 0:
            self.modifications_made = True
            self._rebuild_rows()
            self.status_message = (f"Stripped {result['tags_removed']:,} tags "
                                   f"from {result['segments_modified']:,} segments")
        else:
            self.status_message = "No inline tags found."

    def _op_csv_export(self):
        """Export to CSV."""
        output = self.editor._generate_output_path('_export').replace('.tmx', '.csv')
        result = self._input_dialog("Export CSV", "Output file:", output)
        if result:
            try:
                self.editor.export_to_csv(result)
                self.status_message = f"Exported CSV: {Path(result).name}"
            except Exception as e:
                self.status_message = f"Export error: {e}"

    def _op_statistics(self):
        """Show statistics dialog."""
        stats = self.editor.get_statistics()
        msg = (f"File: {stats['file']}\n"
               f"Languages: {stats['source_lang']} -> {stats['target_lang']}\n"
               f"\n"
               f"Total TUs:         {stats['total_tus']:>10,}\n"
               f"Empty/missing:     {stats['empty_segments']:>10,}\n"
               f"Exact duplicates:  {stats['exact_duplicates']:>10,}\n"
               f"Segments w/ tags:  {stats['segments_with_tags']:>10,}")
        self._message_dialog("Statistics", msg)

    def _op_merge(self):
        """Merge another TMX file."""
        path = self._file_dialog("Merge TMX File")
        if not path or not os.path.isfile(path):
            self.status_message = "Merge cancelled."
            return

        try:
            # Suppress print output
            old_stdout = sys.stdout
            sys.stdout = open(os.devnull, 'w')
            try:
                result = self.editor.merge_from(path, duplicate_strategy='skip')
            finally:
                sys.stdout.close()
                sys.stdout = old_stdout

            if result['added'] > 0:
                self.modifications_made = True
                self._rebuild_rows()
            self.status_message = (f"Merge: +{result['added']:,} added, "
                                   f"{result['skipped']:,} skipped")
        except Exception as e:
            self.status_message = f"Merge error: {e}"

    def _op_open(self):
        """Open a new file."""
        if self.modifications_made:
            if not self._confirm_dialog("Unsaved Changes",
                                        "Discard unsaved changes?"):
                return

        path = self._file_dialog("Open TMX File")
        if path and os.path.isfile(path):
            self._load_file(path)
            self.modifications_made = False

    # ──────────────────────────────────────────────
    # Dropdown menu handling
    # ──────────────────────────────────────────────

    def _handle_menu_action(self):
        """Execute the currently selected menu action."""
        if not self.active_menu:
            return

        items = self.MENU_ITEMS[self.active_menu]
        label, _ = items[self.active_menu_item]
        self.active_menu = None

        if label == 'Open...':
            self._op_open()
        elif label == 'Save':
            self._op_save()
        elif label == 'Save As...':
            self._op_save()
        elif label == 'Export CSV...':
            self._op_csv_export()
        elif label == 'Quit':
            self._try_quit()
        elif label == 'Remove Exact Duplicates':
            self._op_dedup()
        elif label == 'Find Fuzzy Duplicates...':
            self._op_fuzzy()
        elif label == 'Remove Empty Segments':
            self._op_remove_empty()
        elif label == 'Strip Inline Tags':
            self._op_strip_tags()
        elif label == 'Show All':
            self.current_filter = 'all'
            self._apply_filter()
            self.status_message = "Filter: All"
        elif label == 'Show Duplicates Only':
            self.current_filter = 'dup'
            self._apply_filter()
            self.status_message = f"Filter: Duplicates ({len(self.filtered_rows):,})"
        elif label == 'Show Empty Only':
            self.current_filter = 'empty'
            self._apply_filter()
            self.status_message = f"Filter: Empty ({len(self.filtered_rows):,})"
        elif label == 'Show Tagged Only':
            self.current_filter = 'tagged'
            self._apply_filter()
            self.status_message = f"Filter: Tagged ({len(self.filtered_rows):,})"
        elif label == 'Merge TMX File...':
            self._op_merge()
        elif label == 'Statistics':
            self._op_statistics()

    def _try_quit(self):
        """Try to quit, checking for unsaved changes."""
        if self.modifications_made:
            if self._confirm_dialog("Quit",
                                    "Unsaved changes will be lost.\nQuit anyway?"):
                raise SystemExit()
        else:
            raise SystemExit()

    # ──────────────────────────────────────────────
    # Main loop
    # ──────────────────────────────────────────────

    def _main_loop(self):
        """Main event loop."""
        while True:
            self._draw()

            try:
                key = self.stdscr.getch()
            except KeyboardInterrupt:
                self._try_quit()
                continue

            try:
                self._handle_key(key)
            except SystemExit:
                return

    def _handle_key(self, key: int):
        """Handle a keypress."""

        # ── Dropdown menu navigation ──
        if self.active_menu:
            items = self.MENU_ITEMS[self.active_menu]

            if key == curses.KEY_DOWN:
                self.active_menu_item = (self.active_menu_item + 1) % len(items)
                while items[self.active_menu_item][0] == '─':
                    self.active_menu_item = (self.active_menu_item + 1) % len(items)
            elif key == curses.KEY_UP:
                self.active_menu_item = (self.active_menu_item - 1) % len(items)
                while items[self.active_menu_item][0] == '─':
                    self.active_menu_item = (self.active_menu_item - 1) % len(items)
            elif key == curses.KEY_LEFT:
                menu_names = list(self.MENU_ITEMS.keys())
                idx = menu_names.index(self.active_menu)
                self.active_menu = menu_names[(idx - 1) % len(menu_names)]
                self.active_menu_item = 0
            elif key == curses.KEY_RIGHT:
                menu_names = list(self.MENU_ITEMS.keys())
                idx = menu_names.index(self.active_menu)
                self.active_menu = menu_names[(idx + 1) % len(menu_names)]
                self.active_menu_item = 0
            elif key in (ord('\n'), ord('\r')):
                self._handle_menu_action()
            elif key == 27:  # ESC
                self.active_menu = None
            return

        # ── Table navigation ──
        if key == curses.KEY_DOWN:
            if self.selected_row < len(self.filtered_rows) - 1:
                self.selected_row += 1
        elif key == curses.KEY_UP:
            if self.selected_row > 0:
                self.selected_row -= 1
        elif key == curses.KEY_NPAGE:  # Page Down
            visible = self.height - 6
            self.selected_row = min(self.selected_row + visible,
                                    len(self.filtered_rows) - 1)
        elif key == curses.KEY_PPAGE:  # Page Up
            visible = self.height - 6
            self.selected_row = max(self.selected_row - visible, 0)
        elif key == curses.KEY_HOME:
            self.selected_row = 0
            self.scroll_offset = 0
        elif key == curses.KEY_END:
            self.selected_row = max(0, len(self.filtered_rows) - 1)

        # ── F-keys ──
        elif key == curses.KEY_F2:
            self._op_save()
        elif key == curses.KEY_F3:
            self._op_open()
        elif key == curses.KEY_F5:
            self._op_csv_export()
        elif key == curses.KEY_F6:
            self._op_dedup()
        elif key == curses.KEY_F7:
            self._op_fuzzy()
        elif key == curses.KEY_F8:
            self._op_remove_empty()
        elif key == curses.KEY_F9:
            self._op_statistics()
        elif key == curses.KEY_F10:
            self._try_quit()

        # ── Menu bar activation ──
        elif key == 27 or key == curses.KEY_F1:  # ESC or F1
            self.active_menu = list(self.MENU_ITEMS.keys())[0]
            self.active_menu_item = 0

        # ── Filter shortcuts ──
        elif key == ord('a') or key == ord('A'):
            self.current_filter = 'all'
            self._apply_filter()
            self.status_message = "Filter: All"
        elif key == ord('d') or key == ord('D'):
            self.current_filter = 'dup'
            self._apply_filter()
            self.status_message = f"Filter: Duplicates ({len(self.filtered_rows):,})"
        elif key == ord('e') or key == ord('E'):
            self.current_filter = 'empty'
            self._apply_filter()
            self.status_message = f"Filter: Empty ({len(self.filtered_rows):,})"
        elif key == ord('t') or key == ord('T'):
            self.current_filter = 'tagged'
            self._apply_filter()
            self.status_message = f"Filter: Tagged ({len(self.filtered_rows):,})"

        # ── Ctrl+T for strip tags ──
        elif key == 20:  # Ctrl+T
            self._op_strip_tags()

        # ── Ctrl+M for merge ──
        elif key == 13:  # Ctrl+M (same as Enter on some terminals)
            pass  # Avoid conflict with Enter
        elif key == ord('m') or key == ord('M'):
            # Alt+M fallback for merge
            pass

        # ── Quit shortcuts ──
        elif key == ord('q') or key == ord('Q'):
            self._try_quit()


# ══════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════

def run_tui(file_path: str = None):
    """Launch the TUI. Called from tmx_editor.py --gui."""
    def _main(stdscr):
        app = TMXTui(stdscr, file_path=file_path)
        app.run()

    try:
        curses.wrapper(_main)
    except SystemExit:
        pass


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else None
    run_tui(path)
