"""std/tools/bash/box.py: BOX, how a viewer shows a bash call: a live terminal while the command runs, and its output after."""

from __future__ import annotations

import json
import time
from collections.abc import Hashable

from llvim.std.conversation import Entry
from llvim.std.panels.logviewer.ansi import RESET, pad, width, wrap
from llvim.std.panels.logviewer.box import Box, Host, Renderer
from llvim.std.tmux import Embedded, Snapshot, TmuxError
from llvim.std.tools.bash.terminal import CALL_OPTION
from llvim.std.tools.calls import CALL, RESULT, START, by_user, call_id, kind, name

GREY, CYAN, BLUE, RED, DIM = "\x1b[38;5;245m", "\x1b[1;36m", "\x1b[38;5;110m", "\x1b[38;5;203m", "\x1b[2m"
RESULT_ROWS = 20  # rows of a finished command's output that the box shows
LIVE_ROWS = 14  # rows of a running command's terminal
FRAME = 0.03  # seconds between looks at the terminal
SEARCH = (
    0.2  # seconds between looks for the terminal of a call, which the runner starts a moment after the call is written
)
GIVE_UP = 10.0  # after this long without finding it, look only every few seconds (the runner may not be running)


class BashBox(Box):
    def __init__(self, host: Host, messages: list[Entry]):
        super().__init__(host, messages)
        self.call = self.result = None
        self.live: Embedded | None = None  # our view of the pane, while the command runs
        self.snapshot: Snapshot | None = None
        self.focused = False
        self.unavailable = False  # the pane could not be shown (not in tmux, or it was gone)
        self._watching = False
        self._read(messages)
        host.on_messages(self, self.on_messages)
        host.layout(self, self.rows)
        host.focusable(self, lambda: self.focusable)
        host.on_focus(self, self.set_focus)
        host.on_key(self, self.key)
        host.cursor(self, self.cursor)
        host.text(self, self.text_of)
        self._watch()

    def _read(self, messages: list[Entry]) -> None:
        by = {kind(m): m for m in messages}
        self.call, self.result = by.get(CALL), by.get(RESULT)

    def on_messages(self, messages: list[Entry]) -> None:
        self.messages = messages
        self._read(messages)
        if self.result is not None:
            self.live = None  # done: what it printed is in the result
        self._watch()
        self.changed()

    def arguments(self) -> dict:
        try:
            arguments = json.loads((self.call.content if self.call else "") or "{}")
            return arguments if isinstance(arguments, dict) else {}
        except ValueError:
            return {}

    @property
    def command(self) -> str:
        return str(self.arguments().get("command") or (self.call.content if self.call else "") or "")

    @property
    def interactive(self) -> bool:
        return bool(self.arguments().get("interactive"))

    @property
    def focusable(self) -> bool:
        """The user may type into it: it is running, it asked for that, and we can see it."""
        return self.live is not None and self.interactive and not (self.snapshot and self.snapshot.dead)

    def _watch(self) -> None:
        if (
            self.host.live
            and not self._watching
            and self.call is not None
            and self.result is None
            and call_id(self.call)
        ):
            self._watching = True
            self.host.start(self.update)

    def update(self) -> None:
        """Runs beside the viewer while the command runs: find its terminal, attach, and keep its screen in step."""
        started = time.monotonic()
        try:
            while self.live is None and not self.closed.is_set() and self.result is None:
                self.live = Embedded.find(
                    self.host.control(), CALL_OPTION, call_id(self.call), max(self.host.cols - 4, 10), LIVE_ROWS
                )
                if self.live is None:  # the runner starts it a moment after the call is written
                    self.closed.wait(SEARCH if time.monotonic() - started < GIVE_UP else 2.0)
        except (TmuxError, OSError, RuntimeError):  # not in tmux, or it has finished and gone
            self.unavailable = True
            self.changed()
            return
        if self.live is None:
            return
        if by_user(self.call) and self.focusable:
            self.host.request_focus(self)  # the user opened it themselves (/bash): they want to type in it now
        try:
            while not self.closed.is_set() and self.result is None:
                live = self.live
                if live is None:
                    break
                columns = max(self.host.cols - 4, 10)
                if columns != live.columns:
                    live.resize(columns, LIVE_ROWS)
                shot = live.snapshot()
                if shot != self.snapshot:
                    self.snapshot = shot
                    self.changed()
                self.closed.wait(FRAME)
        except TmuxError:  # the runner has closed it: the result is on its way
            pass
        finally:
            self.live, self.focused = None, False
            self.changed()

    def set_focus(self, focused: bool) -> None:
        self.focused = focused
        self.changed()

    def key(self, raw: bytes) -> None:
        if (live := self.live) is not None:  # read once: ``update`` drops it, on its own thread, when the command ends
            try:
                live.send(raw)
            except TmuxError:
                pass

    def cursor(self) -> tuple[int, int] | None:
        snapshot = self.snapshot
        if self.focused and self.live is not None and snapshot and snapshot.cursor:
            cx, cy = snapshot.cursor
            return 2 + cx, 1 + cy  # inside the border and its space
        return None

    def rows(self, cols: int) -> list[str]:
        inner = max(cols - 4, 1)
        failed = bool(
            self.result
            and (
                self.result.extra.get("error") or self.result.content.rstrip().split("\n")[-1].startswith("[exit code")
            )
        )
        colour = CYAN if self.focused else BLUE if self.live is not None else RED if failed else GREY
        head = f"╭─ $ {self.command.split(chr(10))[0]} "
        if width(head) > cols - 3:  # a long command is cut, not wrapped
            head = wrap(head, max(cols - 5, 1))[0].rstrip() + "… "
        hint = " ctrl-] or click outside to leave " if self.focused else " click to type " if self.focusable else ""
        foot = "╰" + hint + "─" * max(cols - 2 - len(hint), 0) + "╯"
        edge = f"{colour}│{RESET}"
        top = f"{colour}{head}{'─' * max(cols - width(head) - 1, 0)}╮{RESET}"
        return (
            [top]
            + [f"{edge} {pad(line, inner)}{RESET} {edge}" for line in self._body(inner)]
            + [f"{colour}{foot}{RESET}"]
        )

    def _body(self, inner: int) -> list[str]:
        if self.result is None:
            if self.snapshot:
                return self.snapshot.lines  # the terminal, or its last screen if we lost it before the result came
            note = "running (no live view)" if self.unavailable else "waiting for the runner…"
            return [f"{DIM}{note}{RESET}"] + ([""] * (LIVE_ROWS - 1) if self.live is not None else [])
        rows = [row for line in (self.result.content or "(no output)").split("\n") for row in wrap(line, inner)]
        if len(rows) > RESULT_ROWS:
            rows = [f"{DIM}… {len(rows) - RESULT_ROWS + 1} rows above{RESET}"] + rows[-(RESULT_ROWS - 1) :]
        return rows or [""]

    def text_of(self) -> str:
        """The plain version: the command, and its output if it is done. Also what a single message of the box prints."""
        out = ""
        if self.call:
            out += f"$ {self.command}\n"
        if self.result is not None:
            out += f"{self.result.content}\n\n"
        return out


def claim(m: Entry) -> Hashable | None:
    """The call, start and result of one bash call go to one box."""
    return call_id(m) if name(m) == "bash" and kind(m) in (CALL, START, RESULT) else None


BOX = Renderer(claim, BashBox, "bash")
