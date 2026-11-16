"""std/panels/logviewer/markdown.py: render, markdown as rows of coloured terminal text for a given width."""

from __future__ import annotations

import re

from llvim.std.panels.logviewer.ansi import RESET, cell_width, expand_tabs, width

BOLD, ITALIC, UNDERLINE, STRIKE = "\x1b[1m", "\x1b[3m", "\x1b[4m", "\x1b[9m"
DIM, LINK, CODE, CODE_BG = "\x1b[38;5;245m", "\x1b[38;5;75m", "\x1b[38;5;216m\x1b[48;5;236m", "\x1b[48;5;235m"
HEADING = ("\x1b[1;4;38;5;81m", "\x1b[1;38;5;81m", "\x1b[1;38;5;110m", "\x1b[1;38;5;245m")  # h1, h2, h3, the rest
BULLET, QUOTE = "• ", "▎ "

Span = tuple[str, str]  # text, and the colour codes it is shown in

FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})\s*([\w+#.-]*)")
HEADING_LINE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*$")
RULE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
ITEM = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$")
TABLE_ROW = re.compile(r"^\s*\|?.*\|.*$")
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
LINK_RE = re.compile(r'\[([^\]]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)')
URL_RE = re.compile(r"https?://[^\s<>)\]]+[^\s<>)\].,;:!?]")
TASK = re.compile(r"^\[([ xX])\]\s+")


# --- inline ---


def inline(s: str, style: str = "") -> list[Span]:
    """The spans of a line of text: pieces with the colour they are shown in."""
    out: list[Span] = []
    buf, i = "", 0

    def flush() -> None:
        nonlocal buf
        if buf:
            out.append((buf, style))
            buf = ""

    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s) and s[i + 1] in "\\`*_{}[]()#+-.!|~<>":
            buf += s[i + 1]
            i += 2
        elif c == "`":
            n = len(s[i:]) - len(s[i:].lstrip("`"))
            end = s.find("`" * n, i + n)
            while end != -1 and s[end + n : end + n + 1] == "`":  # a longer run is not the closer
                end = s.find("`" * n, end + 1 + n)
            if end == -1:
                buf += s[i : i + n]
                i += n
                continue
            flush()
            out.append((s[i + n : end].strip() or " ", CODE))
            i = end + n
        elif c == "[" and (m := LINK_RE.match(s, i)):
            flush()
            out += inline(m[1], style + LINK + UNDERLINE)
            if m[1] != m[2]:
                out.append((f" ({m[2]})", DIM))
            i = m.end()
        elif c == "h" and (m := URL_RE.match(s, i)):
            flush()
            out.append((m[0], style + LINK + UNDERLINE))
            i = m.end()
        elif c in "*_~" and (found := emphasis(s, i)):
            marker, inner, end = found
            flush()
            added = {"**": BOLD, "__": BOLD, "~~": STRIKE}.get(marker, ITALIC)
            out += inline(inner, style + added)
            i = end
        else:
            buf += c
            i += 1
    flush()
    return out


def emphasis(s: str, i: int) -> tuple[str, str, int] | None:
    """``**bold**``, ``*italic*``, ``~~strike~~`` starting at ``i``: (marker, what is inside, where it ends), or None."""
    c = s[i]
    marker = s[i : i + 2] if s[i : i + 2] in ("**", "__", "~~") else c
    if c == "~" and marker != "~~":
        return None
    if c == "_" and i > 0 and (s[i - 1].isalnum()):  # snake_case is not emphasis
        return None
    start = i + len(marker)
    if start >= len(s) or s[start].isspace():
        return None
    end = s.find(marker, start + 1)
    while end != -1:
        before, after = s[end - 1], s[end + len(marker) : end + len(marker) + 1]
        if not before.isspace() and not (c == "_" and after.isalnum()) and not (len(marker) == 1 and after == c):
            return marker, s[start:end], end + len(marker)
        end = s.find(marker, end + 1)
    return None


# --- wrapping ---


def words(spans: list[Span]) -> list[tuple[str, str]]:
    """Spans as words and the single spaces between them (a space is ``(" ", style)``)."""
    out: list[tuple[str, str]] = []
    for text, style in spans:
        for part in re.split(r"(\s+)", text):
            if part:
                out.append((" ", style) if part.isspace() else (part, style))
    return out


def paint(pieces: list[Span]) -> str:
    return "".join(f"{style}{text}{RESET}" if style else text for text, style in pieces)


def wrap_spans(spans: list[Span], cols: int) -> list[str]:
    """Spans cut into rows of at most ``cols`` cells, at the spaces where it can be (a word longer than a row is broken)."""
    cols = max(cols, 1)
    rows: list[list[Span]] = []
    row: list[Span] = []
    used = 0
    for text, style in words(spans):
        if text == " ":
            if row:  # a space at the start of a row is dropped
                row.append((" ", style))
                used += 1
            continue
        w = width(text)
        if used + w > cols and row:
            while row and row[-1][0] == " ":
                row.pop()
            rows.append(row)
            row, used = [], 0
        while w > cols:  # a word too long for a row
            head, taken = "", 0
            for ch in text:
                if taken + cell_width(ch) > cols:
                    break
                head, taken = head + ch, taken + cell_width(ch)
            rows.append([(head, style)])
            text = text[len(head) :]
            w = width(text)
        row.append((text, style))
        used += w
    while row and row[-1][0] == " ":
        row.pop()
    if row or not rows:
        rows.append(row)
    return [paint(r) for r in rows]


# --- blocks ---


FOREGROUND = re.compile(r"38;5;\d+")


def render(text: str, cols: int, tone: str | None = None) -> list[str]:
    """The rows of this markdown at this width. With ``tone`` (a colour code) everything is in that colour, the styles still showing."""
    lines = [expand_tabs(l.rstrip("\r")) for l in text.split("\n")]
    rows = blocks(lines, max(cols, 8))
    if tone is None:
        return rows
    shade = FOREGROUND.search(tone)[0]
    return [tone + FOREGROUND.sub(shade, row).replace(RESET, RESET + tone) + RESET for row in rows]


def starts_block(line: str, nxt: str | None) -> bool:
    return bool(
        FENCE.match(line) or HEADING_LINE.match(line) or RULE.match(line) or line.lstrip().startswith(">") or ITEM.match(line)
        or (nxt is not None and "|" in line and TABLE_RULE.match(nxt) and "-" in nxt)
    )  # fmt: skip


def blocks(lines: list[str], cols: int, tight: bool = False) -> list[str]:
    """The rows of these lines. ``tight`` (inside a list item) leaves no blank row between blocks."""
    out: list[str] = []

    def add(rows: list[str]) -> None:
        if out and rows and out[-1] != "" and not tight:
            out.append("")  # one blank row between blocks
        out.extend(rows)

    i = 0
    while i < len(lines):
        line = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        if not line.strip():
            i += 1
        elif m := FENCE.match(line):
            j = i + 1
            while j < len(lines) and not (lines[j].strip().startswith(m[1][0] * len(m[1])) and not lines[j].strip().strip(m[1][0])):
                j += 1
            add(code(lines[i + 1 : j], m[2], cols))  # an unclosed fence (still streaming) runs to the end
            i = j + 1
        elif m := HEADING_LINE.match(line):
            style = HEADING[min(len(m[1]), 4) - 1]
            add(wrap_spans(inline(m[2], style), cols))
            i += 1
        elif RULE.match(line):
            add([f"{DIM}{'─' * cols}{RESET}"])
            i += 1
        elif line.lstrip().startswith(">"):
            j = i
            while j < len(lines) and lines[j].lstrip().startswith(">"):
                j += 1
            inner = [re.sub(r"^\s*>\s?", "", l) for l in lines[i:j]]
            add([f"{DIM}{QUOTE}{RESET}{row}" for row in blocks(inner, cols - 2)])
            i = j
        elif ITEM.match(line):
            i = items(lines, i, cols, add)
        elif nxt is not None and "|" in line and TABLE_RULE.match(nxt) and "-" in nxt:
            j = i + 2
            while j < len(lines) and lines[j].strip() and "|" in lines[j]:
                j += 1
            add(table(lines[i], nxt, lines[i + 2 : j], cols))
            i = j
        else:
            j = i + 1
            while j < len(lines) and lines[j].strip() and not starts_block(lines[j], lines[j + 1] if j + 1 < len(lines) else None):
                j += 1
            add(wrap_spans(inline(" ".join(l.strip() for l in lines[i:j])), cols))
            i = j
    return out


def code(lines: list[str], language: str, cols: int) -> list[str]:
    """A fenced block: the lines on a darker ground as wide as the screen, with the language over it."""
    inner = max(cols - 2, 1)
    rows = [f"{CODE_BG}{DIM} {language}{' ' * (cols - width(language) - 1)}{RESET}"] if language else []
    for line in lines or [""]:
        pieces = [line[k : k + inner] for k in range(0, len(line), inner)] if line.isascii() else cut_cells(line, inner)
        for piece in pieces or [""]:
            rows.append(f"{CODE_BG} {piece}{' ' * (inner - width(piece))} {RESET}")
    return rows


def cut_cells(line: str, cols: int) -> list[str]:
    out, cur, used = [], "", 0
    for ch in line:
        w = cell_width(ch)
        if used + w > cols and cur:
            out.append(cur)
            cur, used = "", 0
        cur, used = cur + ch, used + w
    return out + [cur]


def items(lines: list[str], i: int, cols: int, add) -> int:
    """The list starting at line ``i``: returns where it ends. Items nest by indentation."""
    first = ITEM.match(lines[i])
    base = len(first[1])
    rows: list[str] = []
    while i < len(lines) and (m := ITEM.match(lines[i])) and len(m[1]) == base:
        marker, content = m[2], m[3]
        body = [content]
        i += 1
        indent = base + len(marker) + 1
        while i < len(lines):
            nxt = lines[i]
            if not nxt.strip():
                if i + 1 < len(lines) and len(lines[i + 1]) - len(lines[i + 1].lstrip()) >= indent and lines[i + 1].strip():
                    body.append("")  # a blank line inside an item
                    i += 1
                    continue
                break
            lead = len(nxt) - len(nxt.lstrip())
            if lead >= indent or (lead > base and not ITEM.match(nxt)):
                body.append(nxt[min(lead, indent) :])
                i += 1
            elif lead > base:
                body.append(nxt[min(lead, indent) :])
                i += 1
            else:
                break
        task = TASK.match(body[0])
        symbol = BULLET
        if task:
            symbol, body[0] = ("☑ " if task[1] != " " else "☐ "), body[0][task.end() :]
        elif marker[0].isdigit():
            symbol = marker + " "
        pad = " " * (width(symbol))
        inner = blocks(body, cols - base - width(symbol), tight=True)
        for k, row in enumerate(inner or [""]):
            rows.append(f"{' ' * base}{DIM if k == 0 else ''}{symbol if k == 0 else pad}{RESET if k == 0 else ''}{row}")
    add(rows)
    return i


def cells(line: str) -> list[str]:
    parts = re.split(r"(?<!\\)\|", line.strip())
    if parts and not parts[0].strip():
        parts = parts[1:]
    if parts and not parts[-1].strip():
        parts = parts[:-1]
    return [p.strip().replace("\\|", "|") for p in parts]


def table(head: str, rule: str, body: list[str], cols: int) -> list[str]:
    """A table with borders, columns fitted to the width (the widest are narrowed and their cells wrapped)."""
    header = cells(head)
    aligns = [("right" if c.endswith(":") and not c.startswith(":") else "center" if c.startswith(":") and c.endswith(":") else "left") for c in cells(rule)]
    n = len(header)
    grid = [header] + [(cells(r) + [""] * n)[:n] for r in body]
    spans = [[inline(c, BOLD if r == 0 else "") for c in row] for r, row in enumerate(grid)]
    natural = [max(max((width("".join(t for t, _ in s)) for s in (spans[r][c] for r in range(len(grid)))), default=1), 1) for c in range(n)]
    sizes = list(natural)
    room = cols - (3 * n + 1)
    while sum(sizes) > max(room, n * 3):
        widest = max(range(n), key=lambda c: sizes[c])
        if sizes[widest] <= 3:
            break
        sizes[widest] -= 1
    line = lambda l, m, r: f"{DIM}{l}{m.join('─' * (s + 2) for s in sizes)}{r}{RESET}"  # noqa: E731
    bar = f"{DIM}│{RESET}"
    out = [line("┌", "┬", "┐")]
    for r, row in enumerate(spans):
        wrapped = [wrap_spans(s, sizes[c]) or [""] for c, s in enumerate(row)]
        for k in range(max(len(w) for w in wrapped)):
            cellrows = []
            for c in range(n):
                text = wrapped[c][k] if k < len(wrapped[c]) else ""
                gap = sizes[c] - width(text)
                a = aligns[c] if c < len(aligns) else "left"
                left = gap if a == "right" else gap // 2 if a == "center" else 0
                cellrows.append(" " + " " * left + text + " " * (gap - left) + " ")
            out.append(bar + bar.join(cellrows) + bar)
        if r == 0:
            out.append(line("├", "┼", "┤"))
    out.append(line("└", "┴", "┘"))
    return out
