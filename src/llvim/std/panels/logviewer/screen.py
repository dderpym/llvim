"""std/panels/logviewer/screen.py: Screen, the terminal taken over: raw input, the mouse, and drawing only the rows that changed."""

from __future__ import annotations

import os
import select
import signal
import sys
import termios
import tty
from contextlib import contextmanager

from llvim.std.panels.keys import DOWN, END, HOME, PAGE_DOWN, PAGE_UP, UP, WHEEL_DOWN, WHEEL_UP, Key, Mouse, parse  # noqa: F401  (re-exported)

SCREEN, MOUSE, PASTE = "\x1b[?1049h\x1b[?25l", "\x1b[?1002h\x1b[?1006h", "\x1b[?2004h\x1b[>4;1m"  # alternate screen and no cursor; mouse with drags; bracketed paste
ENTER = SCREEN + MOUSE
LEAVE = "\x1b[>4;0m\x1b[?2004l\x1b[?1006l\x1b[?1002l\x1b[?25h\x1b[?1049l"


class Screen:
    """Takes over the terminal while in use. ``draw`` writes only the rows that differ from the last frame."""

    def __init__(self, fd_in: int | None = None, out=None, mouse: bool = True, paste: bool = False):
        self.mouse, self.paste = mouse, paste  # whether to ask the terminal for the mouse, and for pastes to be marked
        self.fd_in = sys.stdin.fileno() if fd_in is None else fd_in
        self.out = out if out is not None else sys.stdout
        self.shown: list[str] = []
        self.cursor: tuple[int, int] | None = None
        self.resized, self._saved = False, None
        self._wake_r, self._wake_w = os.pipe()  # a resize wakes the loop that waits on input

    def __enter__(self) -> Screen:
        self._saved = termios.tcgetattr(self.fd_in)
        tty.setraw(self.fd_in)
        os.set_blocking(self._wake_r, False)
        os.set_blocking(self._wake_w, False)
        signal.set_wakeup_fd(self._wake_w)
        signal.signal(signal.SIGWINCH, lambda *a: setattr(self, "resized", True))
        self._write(SCREEN + (MOUSE if self.mouse else "") + (PASTE if self.paste else ""))
        return self

    def __exit__(self, *exc) -> None:
        self._write(LEAVE)
        signal.set_wakeup_fd(-1)
        signal.signal(signal.SIGWINCH, signal.SIG_DFL)
        termios.tcsetattr(self.fd_in, termios.TCSADRAIN, self._saved)
        os.close(self._wake_r)
        os.close(self._wake_w)

    @contextmanager
    def cbreak(self):
        """Let ctrl-c interrupt again for a while (raw mode takes the signal keys away), for something that blocks."""
        tty.setcbreak(self.fd_in)
        try:
            yield
        finally:
            tty.setraw(self.fd_in)

    def size(self) -> tuple[int, int]:
        """(columns, rows)"""
        s = os.get_terminal_size(self.fd_in)
        return s.columns, s.lines

    def fds(self) -> list[int]:
        return [self.fd_in, self._wake_r]

    def read(self) -> list[Key | Mouse]:
        """What is waiting on the keyboard and mouse. Also notes a resize."""
        try:
            os.read(self._wake_r, 4096)  # drain the wake-up bytes
        except BlockingIOError:
            pass
        if select.select([self.fd_in], [], [], 0)[0]:
            data = os.read(self.fd_in, 65536)
            if not data:
                raise EOFError
            return parse(data)
        return []

    def invalidate(self) -> None:
        self.shown = []

    def draw(self, rows: list[str], cursor: tuple[int, int] | None = None) -> None:
        """Show these rows (already as wide as the screen). ``cursor`` is (column, row) or None to hide it."""
        out = []
        for y, row in enumerate(rows):
            if y >= len(self.shown) or self.shown[y] != row:
                out.append(f"\x1b[{y + 1};1H{row}\x1b[0m\x1b[K")
        if len(self.shown) > len(rows):
            out.append(f"\x1b[{len(rows) + 1};1H\x1b[J")
        if cursor != self.cursor or out:
            out.append(f"\x1b[{cursor[1] + 1};{cursor[0] + 1}H\x1b[?25h" if cursor else "\x1b[?25l")
        self.shown, self.cursor = list(rows), cursor
        if out:
            self._write("\x1b[?2026h" + "".join(out) + "\x1b[?2026l")  # drawn in one go where the terminal supports it

    def copy(self, text: str) -> None:
        """Put text on the clipboard of the terminal, with the OSC 52 escape (tmux passes it on, and keeps it in its own buffer)."""
        import base64

        self._write(f"\x1b]52;c;{base64.b64encode(text.encode()[:1_000_000]).decode()}\x07")

    def _write(self, text: str) -> None:
        self.out.write(text)
        self.out.flush()
