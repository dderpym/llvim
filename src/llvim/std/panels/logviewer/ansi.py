"""std/panels/logviewer/ansi.py: text with colour codes, measured, wrapped, cut and highlighted in terminal cells."""

import re
import unicodedata

RESET = "\x1b[0m"
_TOKEN = re.compile(r"(\x1b\[[0-9;:]*[ -/]*[@-~])|(\x1b\][^\x07\x1b]*(?:\x07|\x1b\\))|(\x1b.?)|(.)", re.S)
_RESETS = re.compile(r"\x1b\[0?m")
_NOT_PLAIN = re.compile(r"[^\x20-\x7e]")  # anything but printable ASCII needs the careful path
_SGR = re.compile(r"(\x1b\[[0-9;]*m)")  # a colour code, kept by split


def cell_width(ch: str) -> int:
    """0 for a combining mark, 2 for a wide (CJK, emoji) character, else 1."""
    if unicodedata.category(ch) in ("Mn", "Me", "Cf"):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def width(text: str) -> int:
    """Cells the text takes on screen, not counting its colour codes."""
    if text.isascii():
        stripped = _SGR.sub("", text)
        if not _NOT_PLAIN.search(stripped):
            return len(stripped)  # nearly all text: one cell a character, and colour codes none
    return sum(cell_width(m[4]) for m in _TOKEN.finditer(text) if m[4] and m[4] >= " ")


def expand_tabs(line: str, size: int = 8) -> str:
    """Tabs as spaces to the next stop, counting columns by what is shown (colour codes take none)."""
    if "\t" not in line:
        return line
    out, col = [], 0
    for m in _TOKEN.finditer(line):
        if m[4] == "\t":
            out.append(" " * (size - col % size))
            col += size - col % size
        else:
            out.append(m[0])
            col += cell_width(m[4]) if m[4] and m[4] >= " " else 0
    return "".join(out)


def wrap(line: str, cols: int) -> list[str]:
    """One line cut into rows of at most ``cols`` cells. A colour carries over to the next row; every row ends reset.

    Only colour codes survive: other escapes (moving the cursor, setting a title) are dropped, since the viewer
    owns the screen.
    """
    if line.isascii() and not _NOT_PLAIN.search(line):  # nearly all text: cut it where it is long, nothing to track
        cols = max(cols, 1)
        return [line[i : i + cols] for i in range(0, len(line), cols)] or [""]
    if line.isascii() and not _NOT_PLAIN.search(_SGR.sub("", line)):  # plain text with colours: cut the text between the codes
        return _wrap_coloured(line, max(cols, 1))
    rows: list[str] = []
    cur, used, style = "", 0, ""
    for m in _TOKEN.finditer(expand_tabs(line)):
        csi, osc, esc, ch = m.groups()
        if csi:
            if csi.endswith("m"):
                style = "" if _RESETS.fullmatch(csi) else (style if not csi.startswith("\x1b[0;") else "") + csi
                cur += csi
            continue
        if osc or esc or ch < " ":
            continue
        w = cell_width(ch)
        if used + w > cols and used > 0:
            rows.append(cur + (RESET if style else ""))
            cur, used = style, 0
        cur += ch
        used += w
    rows.append(cur + (RESET if style else ""))
    return rows


def _wrap_coloured(line: str, cols: int) -> list[str]:
    """``wrap`` for printable ASCII and colour codes only, which is what nearly all of the viewer's text is."""
    rows: list[str] = []
    cur, used, style = "", 0, ""
    for i, part in enumerate(_SGR.split(line)):
        if i % 2:  # a colour code: it takes no room
            style = "" if _RESETS.fullmatch(part) else ("" if part.startswith("\x1b[0;") else style) + part
            cur += part
            continue
        pos = 0
        while pos < len(part):
            if used == cols:  # full, and there is more to place
                rows.append(cur + (RESET if style else ""))
                cur, used = style, 0
            piece = part[pos : pos + cols - used]
            cur, used, pos = cur + piece, used + len(piece), pos + len(piece)
    rows.append(cur + (RESET if style else ""))
    return rows


def pad(row: str, cols: int) -> str:
    """The row filled with spaces to exactly ``cols`` cells (cut if it is longer)."""
    row = expand_tabs(row)
    w = width(row)
    return row + " " * (cols - w) if w <= cols else wrap(row, cols)[0]


def strip(text: str) -> str:
    """The text without colour codes or any other escape."""
    if "\x1b" not in text:
        return text
    return "".join(m[4] for m in _TOKEN.finditer(text) if m[4] and m[4] >= " ")


def cut(text: str, start: int, end: int | None = None) -> str:
    """The characters of plain text that fall in cells ``start`` up to ``end`` (a wide character goes with its first cell)."""
    out, col = [], 0
    for ch in text:
        w = cell_width(ch)
        if col >= start and (end is None or col < end):
            out.append(ch)
        col += w
        if end is not None and col >= end and col > start:
            break
    return "".join(out)


def highlight(row: str, start: int, end: int | None = None) -> str:
    """The row with cells ``start`` up to ``end`` in reverse video, whatever colours it has."""
    out, col, on = [], 0, False
    for m in _TOKEN.finditer(row):
        csi, osc, esc, ch = m.groups()
        if ch is None:  # an escape: colours go through, and put the highlight back after anything that might have ended it
            out.append(m[0])
            if on and csi and csi.endswith("m"):
                out.append("\x1b[7m")
            continue
        if ch < " ":
            out.append(ch)
            continue
        inside = col >= start and (end is None or col < end)
        if inside and not on:
            out.append("\x1b[7m")
        elif on and not inside:
            out.append("\x1b[27m")
        on = inside
        out.append(ch)
        col += cell_width(ch)
    if on:
        out.append("\x1b[27m")
    return "".join(out)
