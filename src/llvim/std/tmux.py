"""std/tmux.py: Control, a quick connection to tmux, and Embedded, a program in a hidden tmux window that another
program shows and types into."""

from __future__ import annotations

import os
import re
import select
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

END = re.compile(rb"%(end|error) \d+ \d+ 1")  # the 1: a reply to a command this client sent, not to tmux's own


class TmuxError(RuntimeError):
    pass


class Control:
    """A tmux control-mode client. ``run`` sends one command and returns its output."""

    def __init__(self, server: list[str], session: str):
        """``server`` selects the tmux server, e.g. ``["-S", "/tmp/tmux-1000/llvim"]``."""
        env = {k: v for k, v in os.environ.items() if k != "TMUX"}  # a control client is not a nested session
        self.proc = subprocess.Popen(
            ["tmux", *server, "-C", "attach-session", "-f", "ignore-size,no-output", "-t", session],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
        )  # fmt: skip
        os.set_blocking(self.proc.stdout.fileno(), False)
        self._buf, self._block, self.closed = b"", None, False
        self._lock = threading.Lock()  # one command at a time: its reply is read straight after it is sent
        self._replies: deque[tuple[bool, str]] = deque()

    @classmethod
    def here(cls) -> Control:
        """A client of the tmux server this program runs in (from ``$TMUX``). Raises TmuxError outside tmux."""
        tmux, pane = os.environ.get("TMUX"), os.environ.get("TMUX_PANE")
        if not tmux or not pane:
            raise TmuxError("not running inside tmux")
        session = subprocess.run(["tmux", "display-message", "-p", "-t", pane, "#{session_id}"], capture_output=True, text=True).stdout.strip()
        return cls(["-S", tmux.split(",")[0]], session)

    def fileno(self) -> int:
        return self.proc.stdout.fileno()

    def pump(self) -> None:
        """Read what tmux has sent, if anything. A call to ``run`` does this itself."""
        try:
            data = os.read(self.fileno(), 65536)
        except BlockingIOError:
            return
        if not data:
            self.closed = True
            return
        self._buf += data
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            self._line(line.rstrip(b"\r"))

    def _line(self, line: bytes) -> None:
        if self._block is not None:
            if m := END.fullmatch(line):
                body = b"\n".join(self._block).decode("utf-8", "replace")
                self._replies.append((m[1] == b"end", body))
                self._block = None
            elif line.startswith(b"%end") or line.startswith(b"%error"):  # the reply to a command that is not ours
                self._block = None
            else:
                self._block.append(line)
        elif line.startswith(b"%begin") and line.endswith(b" 1"):
            self._block = []
        elif line.startswith(b"%begin"):
            self._block = []  # tmux's own: read and ignored, so it does not look like our reply
            self._block.append(b"")
        elif line.startswith(b"%exit"):
            self.closed = True

    def run(self, command: str, timeout: float = 2.0) -> str:
        """Run a tmux command and return what it printed. Raises TmuxError if it fails or tmux does not answer.

        Safe to call from several threads: they take turns.
        """
        with self._lock:
            return self._run(command, timeout)

    def _run(self, command: str, timeout: float) -> str:
        if self.closed:
            raise TmuxError("the tmux connection has closed")
        self._replies.clear()
        try:
            self.proc.stdin.write(command.encode() + b"\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, ValueError):
            self.closed = True
            raise TmuxError("the tmux connection has closed") from None
        deadline = time.monotonic() + timeout
        while not self._replies:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TmuxError(f"tmux did not answer {command.split()[0]}")
            select.select([self.fileno()], [], [], left)
            self.pump()
            if self.closed and not self._replies:
                raise TmuxError("the tmux connection has closed")
        ok, body = self._replies.popleft()
        if not ok:
            raise TmuxError(body.strip() or command.split()[0] + " failed")
        return body

    def close(self) -> None:
        self.proc.kill()
        self.proc.wait()
        self.proc.stdin.close()
        self.proc.stdout.close()
        self.closed = True


@dataclass(frozen=True)
class Snapshot:
    lines: list[str]  # the screen, one string per row, colour codes included
    cursor: tuple[int, int] | None  # (column, row), None when the program hides it
    dead: bool  # the program has exited (its pane is still there, until someone closes it)
    status: int | None  # its exit status, once dead


class Embedded:
    """One program in a hidden tmux window, as big as the rectangle it is shown in."""

    def __init__(self, control: Control, pane: str, columns: int, rows: int, owner: bool):
        self.control, self.pane, self.columns, self.rows, self.owner = control, pane, columns, rows, owner
        self.files: Path | None = None  # the command and wrapper scripts of a program this party started

    STATUS = "@llvim_status"  # the pane option the wrapper sets when the program has exited

    @classmethod
    def start(cls, control: Control, command: str, cwd: str, columns: int, rows: int, options: dict[str, str] | None = None) -> Embedded:
        """Run ``command`` (shell text, any length, any number of lines) in a new hidden window. ``options`` are user options
        (``@name``) set on its pane before the program starts, so another party can find it (see ``find``).

        The command never goes through tmux's command line, which is one line of text with its own quoting: it is written to a file,
        and tmux is told only to run a wrapper script (also a file) that runs it. The pane is never left dead: when the program exits
        the wrapper records its exit status in the pane's ``@llvim_status`` and waits, so tmux has no "Pane is dead" note to draw over
        the screen. ``close`` ends the pane and removes the files.
        """
        # The program waits for a signal before it starts, so the window has its size and a program that exits at once still has
        # its screen to read. ``trap : INT`` keeps ctrl-c from ending the wrapper (the program below it still gets the signal).
        go = f"llvim-go-{os.getpid()}-{time.monotonic_ns()}"
        files = Path(tempfile.mkdtemp(prefix="llvim-term-"))
        (files / "command.sh").write_text(command + "\n")
        (files / "wrapper.sh").write_text(
            f"tmux wait-for {go}\ntrap : INT\nsh {shlex.quote(str(files / 'command.sh'))}\n"
            f'tmux set-option -p -t "$TMUX_PANE" {cls.STATUS} "$?"\nexec sleep 2147483647\n'
        )
        pane = None
        try:
            run = shlex.quote(f"sh {shlex.quote(str(files / 'wrapper.sh'))}")
            pane = control.run(f"new-window -d -P -F '#{{pane_id}}' -n llvim-term -c {shlex.quote(cwd)} {run}").strip()
            for name, value in (options or {}).items():
                control.run(f"set-option -p -t {pane} {name} {shlex.quote(value)}")
            term = cls(control, pane, columns, rows, owner=True)
            term.files = files
            term.resize(columns, rows, force=True)
            control.run(f"wait-for -S {go}")
        except Exception:
            if pane:  # its window would wait for a signal that never comes
                try:
                    control.run(f"kill-pane -t {pane}")
                except TmuxError:
                    pass
            shutil.rmtree(files, ignore_errors=True)
            raise
        return term

    @classmethod
    def find(cls, control: Control, option: str, value: str, columns: int, rows: int) -> Embedded | None:
        """Attach to the pane whose user option ``option`` is ``value``, or None if there is not one (yet)."""
        for line in control.run(f"list-panes -a -F '#{{pane_id}} #{{{option}}}'").splitlines():
            pane, _, found = line.partition(" ")
            if found == value:
                return cls.attach(control, pane, columns, rows)
        return None

    @classmethod
    def attach(cls, control: Control, pane: str, columns: int, rows: int) -> Embedded:
        """Look at (and type into) a program someone else started. Raises TmuxError if the pane is gone."""
        control.run(f"display-message -p -t {pane} x")
        term = cls(control, pane, columns, rows, owner=False)
        term.resize(columns, rows, force=True)
        return term

    def resize(self, columns: int, rows: int, force: bool = False) -> None:
        if force or (columns, rows) != (self.columns, self.rows):
            self.columns, self.rows = columns, rows
            self.control.run(f"resize-window -t {self.pane} -x {columns} -y {rows}")

    def send(self, raw: bytes) -> None:
        """Pass keys through exactly as the terminal sent them."""
        if raw:
            self.control.run(f"send-keys -t {self.pane} -H " + " ".join(f"{b:02x}" for b in raw))

    def snapshot(self) -> Snapshot:
        x, y, visible, status = (self.control.run(
            f"display-message -p -t {self.pane} '#{{cursor_x}} #{{cursor_y}} #{{cursor_flag}} #{{{self.STATUS}}}'"
        ).rstrip("\n").split(" ") + [""] * 4)[:4]  # fmt: skip
        lines = (self.control.run(f"capture-pane -p -e -t {self.pane}").split("\n") + [""] * self.rows)[: self.rows]
        done = status != ""  # the wrapper has recorded how the program ended
        return Snapshot(lines, None if done or visible != "1" else (int(x), int(y)), done, int(status) if done else None)

    def interrupt(self) -> None:
        self.control.run(f"send-keys -t {self.pane} C-c")

    def transcript(self) -> str:
        """Everything the program printed, history included, with lines that wrapped joined back and trailing spaces as the
        program wrote them. Empty rows follow the last line, down to the bottom of the screen."""
        return self.control.run(f"capture-pane -p -J -S - -t {self.pane}")

    def close(self) -> None:
        """End the program and its window, if this party started it."""
        if not self.owner:
            return
        try:
            self.control.run(f"kill-pane -t {self.pane}")
        except TmuxError:
            pass  # already gone
        if self.files is not None:
            shutil.rmtree(self.files, ignore_errors=True)
