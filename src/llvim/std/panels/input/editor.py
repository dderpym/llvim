"""std/panels/input/editor.py: Editor, the line being typed, its cursor and its history, and the keys that edit it."""

from __future__ import annotations

import json
from pathlib import Path

SPACE = " \t\n"
HISTORY = 1000  # entries kept between sessions


class Editor:
    def __init__(self, history: list[str] | None = None):
        self.text, self.cursor = "", 0
        self.history = list(history or [])
        self._at: int | None = None  # the history entry on show, or None when this is a new line
        self._draft = ""  # what was typed before going back through the history

    # --- changing the text ---

    def insert(self, s: str) -> None:
        self.text = self.text[: self.cursor] + s + self.text[self.cursor :]
        self.cursor += len(s)

    def set(self, text: str) -> None:
        self.text, self.cursor = text, len(text)

    def clear(self) -> None:
        self.set("")
        self._at = None

    def backspace(self) -> None:
        if self.cursor:
            self.text = self.text[: self.cursor - 1] + self.text[self.cursor :]
            self.cursor -= 1

    def delete(self) -> None:
        self.text = self.text[: self.cursor] + self.text[self.cursor + 1 :]

    def kill_to_end(self) -> None:
        self.text = self.text[: self.cursor]

    def kill_to_start(self) -> None:
        self.text, self.cursor = self.text[self.cursor :], 0

    def kill_word(self) -> None:
        start = self._word_start()
        self.text, self.cursor = self.text[:start] + self.text[self.cursor :], start

    def newline(self) -> None:
        self.insert("\n")

    # --- moving ---

    def left(self) -> None:
        self.cursor = max(self.cursor - 1, 0)

    def right(self) -> None:
        self.cursor = min(self.cursor + 1, len(self.text))

    def home(self) -> None:
        self.cursor = 0

    def end(self) -> None:
        self.cursor = len(self.text)

    def _word_start(self) -> int:
        i = self.cursor
        while i > 0 and self.text[i - 1] in SPACE:
            i -= 1
        while i > 0 and self.text[i - 1] not in SPACE:
            i -= 1
        return i

    def word_left(self) -> None:
        self.cursor = self._word_start()

    def word_right(self) -> None:
        i = self.cursor
        while i < len(self.text) and self.text[i] in SPACE:
            i += 1
        while i < len(self.text) and self.text[i] not in SPACE:
            i += 1
        self.cursor = i

    # --- the history ---

    def history_prev(self) -> None:
        if self._at is None:
            self._draft, self._at = self.text, len(self.history)
        if self._at > 0:
            self._at -= 1
            self.set(self.history[self._at])

    def history_next(self) -> None:
        if self._at is None:
            return
        self._at += 1
        if self._at >= len(self.history):
            self._at = None
            self.set(self._draft)
        else:
            self.set(self.history[self._at])

    def submit(self) -> str:
        """Take the line: it goes into the history (unless it repeats the last one) and the editor is empty again."""
        text = self.text
        if text.strip() and (not self.history or self.history[-1] != text):
            self.history.append(text)
        self.clear()
        return text


KEYS = {
    b"\x7f": "backspace", b"\x08": "backspace", b"\x1b[3~": "delete", b"\x04": "delete",
    b"\x1b[D": "left", b"\x1bOD": "left", b"\x02": "left", b"\x1b[C": "right", b"\x1bOC": "right", b"\x06": "right",
    b"\x01": "home", b"\x1b[H": "home", b"\x1bOH": "home", b"\x1b[1~": "home",
    b"\x05": "end", b"\x1b[F": "end", b"\x1bOF": "end", b"\x1b[4~": "end",
    b"\x0b": "kill_to_end", b"\x15": "kill_to_start", b"\x17": "kill_word",
    b"\x1bb": "word_left", b"\x1b[1;5D": "word_left", b"\x1b[1;3D": "word_left",
    b"\x1bf": "word_right", b"\x1b[1;5C": "word_right", b"\x1b[1;3C": "word_right",
    b"\x1b[A": "history_prev", b"\x1bOA": "history_prev", b"\x10": "history_prev",
    b"\x1b[B": "history_next", b"\x1bOB": "history_next", b"\x0e": "history_next",
    b"\x1b[27;2;13~": "newline", b"\x1b[13;2u": "newline",  # shift-enter, as modifyOtherKeys and as CSI u send it
}  # fmt: skip


def printable(raw: bytes) -> str | None:
    """The text of a key that is text (one character, or a few that arrived together), else None."""
    try:
        text = raw.decode()
    except UnicodeDecodeError:
        return None
    return text if text and all(c.isprintable() for c in text) else None


def handle(editor: Editor, raw: bytes) -> bool:
    """Apply a key that edits the line. False if it is not one."""
    if name := KEYS.get(raw):
        getattr(editor, name)()
        return True
    if (text := printable(raw)) is not None:
        editor.insert(text)
        return True
    return False


def load_history(path: Path, limit: int = HISTORY) -> list[str]:
    """The entries saved in ``path``, one JSON string a line (a plain line, from an older version, is taken as it is)."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            entry = line
        if isinstance(entry, str) and entry.strip():
            out.append(entry)
    return out[-limit:]


def save_history(path: Path, history: list[str], limit: int = HISTORY) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(e) + "\n" for e in history[-limit:]))
    except OSError:
        pass  # a history that cannot be kept is not worth stopping for
