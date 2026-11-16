"""std/panels/input/view.py: render, what the input bar looks like at a size: the menu above, the prompt below."""

from __future__ import annotations

from llvim.std.panels.input.editor import Editor
from llvim.std.panels.input.menu import Menu
from llvim.std.panels.logviewer.ansi import cell_width, pad, width, wrap

INPUT_ROWS = 3  # the rows of the prompt itself: the pane is this tall until a menu opens above it
MENU_MAX = 8  # suggestions shown at once
PROMPT, CONTINUE = "\x1b[1;36m› \x1b[0m", "  "
DIM, RESET, SELECTED = "\x1b[2m", "\x1b[0m", "\x1b[1;36m"


def wanted(menu: Menu) -> int:
    """How many rows the menu would like (zero when it is shut)."""
    if not menu.shown:
        return 0
    return min(len(menu.items), MENU_MAX) + (1 if len(menu.items) > MENU_MAX else 0)


def prompt_height(editor: Editor, cols: int) -> int:
    """How many rows the text needs (at least the usual three)."""
    return max(len(cut(editor.text, max(cols - 2, 1), editor.cursor)[0]), INPUT_ROWS)


def cut(text: str, cols: int, cursor: int) -> tuple[list[str], tuple[int, int]]:
    """The text cut into rows of at most ``cols`` cells, and where the cursor (an index into the text) is: (row, column)."""
    rows, row, used, at = [], "", 0, None
    for i, ch in enumerate(text):
        if ch == "\n":  # a line break ends the row, and the cursor on it is at the end of the row
            if i == cursor:
                at = (len(rows), used)
            rows.append(row)
            row, used = "", 0
            continue
        w = cell_width(ch)
        if used + w > cols and used > 0:
            rows.append(row)
            row, used = "", 0
        if i == cursor:
            at = (len(rows), used)
        row, used = row + ch, used + w
    if at is None:  # the cursor is at the end, and a full row means it starts the next one
        if used >= cols:
            rows.append(row)
            row, used = "", 0
        at = (len(rows), used)
    return rows + [row], at


def menu_rows(menu: Menu, cols: int, room: int) -> list[str]:
    """The rows of the menu, at most ``room`` of them, the chosen suggestion marked."""
    if not menu.shown or room <= 0:
        return []
    items = menu.items
    visible = min(len(items), MENU_MAX, room)
    first = 0
    if menu.selected is not None and menu.selected >= visible:
        first = menu.selected - visible + 1  # scrolled so the chosen one is in view
    shown = items[first : first + visible]
    name = max(width(s.text) for s in shown) + 2
    out = []
    for i, s in enumerate(shown, first):
        mark, style = ("▸ ", SELECTED) if i == menu.selected else ("  ", "")
        out.append(pad(f"{style}{mark}{s.text}{RESET}{' ' * (name - width(s.text))}{DIM}{s.help}{RESET}", cols))
    if len(items) > first + visible and room > visible:
        out.append(pad(f"{DIM}  … {len(items) - first - visible} more{RESET}", cols))
    return out


def render(editor: Editor, menu: Menu, notice: str, cols: int, rows: int) -> tuple[list[str], tuple[int, int] | None]:
    """The rows to draw in a pane of this size, and the cursor. The prompt sits at the bottom and the menu opens above it."""
    text_rows, (cursor_row, cursor_col) = cut(editor.text, max(cols - 2, 1), editor.cursor)
    height = min(max(len(text_rows), INPUT_ROWS), max(rows, 1))  # the prompt takes what its text needs, the menu what is left
    start = max(0, min(cursor_row - (height - 1), len(text_rows) - height))
    prompt = [(PROMPT if start + i == 0 else CONTINUE) + r for i, r in enumerate(text_rows[start : start + height])]
    if notice and len(prompt) < height:
        prompt.append(f"{DIM}{wrap(notice, cols)[0]}{RESET}")
    prompt = [pad(r, cols) for r in prompt] + [""] * (height - len(prompt))
    menu_part = menu_rows(menu, cols, rows - height)
    grid = [""] * max(rows - height - len(menu_part), 0) + menu_part + prompt
    grid = grid[-rows:]
    cursor_y = len(grid) - height + (cursor_row - start)
    return grid, ((2 + cursor_col, cursor_y) if 0 <= cursor_y < rows else None)
