"""std/panels/logviewer/app.py: Viewer, the screen of the log: it scrolls, selects and copies, and gives keys to boxes."""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Iterable
from contextlib import aclosing
from pathlib import Path
from typing import NamedTuple

from llvim.core import Log, Snapshot
from llvim.std.panels.logviewer.box import Box, Host, Renderer
from llvim.std.panels.logviewer.ansi import cut, highlight, strip
from llvim.std.panels.logviewer.document import Document, Place, Slot
from llvim.std.panels.keys import Outcome, Panes, Redirect, over, route
from llvim.std.panels.logviewer.screen import DOWN, END, HOME, PAGE_DOWN, PAGE_UP, UP, WHEEL_DOWN, WHEEL_UP, Key, Mouse, Screen
from llvim.std.tmux import Control

LEAVE = b"\x1d"  # ctrl-]: a way out of a box that has the keyboard, as in telnet and ssh (clicking outside it is the other)
QUIT = b"\x03"  # ctrl-c, when there is no input bar to give it to
NOTCH = 3  # rows per wheel click


class Spot(NamedTuple):
    """A cell of the log: a slot, a row of it, a column. It stays where it is in the log when the screen scrolls."""

    slot: Slot
    row: int
    col: int


def unbox(piece: str) -> str:
    """Text copied from a box that draws itself, without the lines of its frame."""
    if piece.startswith("╭"):
        return piece.lstrip("╭─ ").rstrip("─╮ ")  # its title
    if piece.startswith("╰"):
        return ""
    if piece.startswith("│"):
        piece = piece[2:] if piece.startswith("│ ") else piece[1:]
        piece = piece.rstrip()
        return piece[:-1].rstrip() if piece.endswith("│") else piece
    return piece


class ViewerHost(Host):
    """What the boxes of a viewer talk to."""

    live = True

    def __init__(self, viewer: Viewer):
        self.viewer, self._control, self._lock = viewer, None, threading.Lock()

    @property
    def cols(self) -> int:  # type: ignore[override]
        return self.viewer.cols

    @property
    def project(self) -> Path:  # type: ignore[override]
        return self.viewer.project

    def changed(self, box: Box | None = None) -> None:
        self.viewer.wake(box)

    def request_focus(self, box: Box) -> None:
        self.viewer.focus_wanted = box
        self.viewer.wake()

    def control(self) -> Control:
        with self._lock:
            if self._control is None or self._control.closed:
                self._control = Control.here()
            return self._control

    def close(self) -> None:
        if self._control:
            self._control.close()


class Viewer:
    def __init__(self, log: Log, project: Path, screen: Screen, panes: Panes | None = None, renderers: Iterable[Renderer] = ()):
        self.log, self.project, self.screen = log, project, screen
        self.host = ViewerHost(self)
        self.doc = Document(self.host, renderers)
        self.snapshot: Snapshot | None = None  # the newest read of the log, not yet given to the document
        self.anchor: Slot | None = None  # where the top of the screen is: a slot, and how many of its rows are above the screen
        self.offset, self.follow, self.dirty = 0, True, True
        self.places: list[Place] = []  # the slots on screen, as of the last frame
        self.cols, self.rows = screen.size()
        self.focus: Slot | None = None
        self.focus_wanted: Box | None = None  # a box asked for the keyboard (see ``Host.request_focus``)
        self.panes = panes or Panes(over(self.host.control))  # where the other panels are, for keys this one does not use
        self.selection: tuple[Spot, Spot] | None = None  # where the user dragged: from, to (in either order)
        self._press: tuple[int, int] | None = None  # the cell the left button went down on, until it comes up
        self._press_spot: Spot | None = None
        self._dragging = False
        self._wake_r, self._wake_w = os.pipe()  # a box's thread says "draw again" here, and wakes the loop
        os.set_blocking(self._wake_r, False)
        os.set_blocking(self._wake_w, False)

    def wake(self, box: Box | None = None) -> None:
        """Something changed (in ``box``, if known). Safe to call from any thread."""
        self.dirty = True
        if box is None:
            self.doc.stale()
        try:
            os.write(self._wake_w, b"x")
        except BlockingIOError:
            pass  # already awake

    # --- focus ---

    def hook(self, box: Box, name: str, *args):
        """Call one of a box's hooks. A box that raises is marked failed and replaced by the fallback."""
        fn = getattr(box.hooks, name)
        if not callable(fn):
            return None
        try:
            return fn(*args)
        except Exception as e:
            box.error = e
            return None

    def focusable(self, box: Box) -> bool:
        f = box.hooks.focusable
        return bool(self.hook(box, "focusable") if callable(f) else f)

    def set_focus(self, slot: Slot | None) -> None:
        if self.focus is not None and self.focus is not slot and self.focus.box is not None:
            self.hook(self.focus.box, "on_focus", False)
        if slot is not None and slot is not self.focus:
            self.hook(slot.box, "on_focus", True)
        self.focus = slot

    def grant_focus(self) -> None:
        """Give the keyboard to the box that asked for it, if it is in the log and focusable, and show the end of the log."""
        box, self.focus_wanted = self.focus_wanted, None
        if box is None:
            return
        slot = next((s for s in self.doc.slots if s.box is box), None)
        if slot is not None and self.focusable(box):
            self.set_focus(slot)
            self.follow = self.dirty = True

    # --- where we are ---

    def top(self) -> tuple[Slot | None, int]:
        """The anchor of the screen now: the end of the log when following it."""
        if self.follow or self.doc._index(self.anchor) is None:
            self.follow = True
            self.anchor, self.offset = self.doc.end_position(self.rows, self.cols)
        return self.anchor, self.offset

    def scroll(self, rows: int) -> None:
        anchor, offset = self.top()
        self.anchor, self.offset, self.follow = self.doc.move(anchor, offset, rows, self.rows, self.cols)

    # --- input ---

    def on_mouse(self, ev: Mouse) -> None:
        base, motion = ev.button & ~(4 | 8 | 16 | 32), ev.button & 32  # without the modifiers and the "moved" flag
        if base == WHEEL_UP:
            self.scroll(-NOTCH)
        elif base == WHEEL_DOWN:
            self.scroll(NOTCH)
        elif base == 0 and motion:  # dragging with the left button down: select
            if self._press is not None and (self._dragging or (ev.x, ev.y) != self._press):
                self.drag(ev.x, ev.y)
        elif base == 0 and ev.press:
            self.selection, self._dragging = None, False
            self._press, self._press_spot = (ev.x, ev.y), self.spot_at(ev.x, ev.y)
        elif base == 0:  # the button came up: the end of a selection, or a click
            if self._dragging:
                self.screen.copy(self.selected_text())
            elif self._press is not None:  # a click gives the keyboard to the box under it, if it takes it, or takes it back
                hit = next((p for p in self.places if p.top <= ev.y < p.top + p.height), None)
                self.set_focus(hit.slot if hit and self.focusable(hit.box) else None)
                if hit and hit.box is not None:
                    self.hook(hit.box, "on_click")
            self._press, self._dragging = None, False

    # --- selecting and copying ---

    def spot_at(self, x: int, y: int) -> Spot | None:
        """The cell of the log under a screen position. Below the last row it is the end of the log."""
        if not self.places:
            return None
        for p in self.places:
            if p.top <= y < p.top + p.height:
                return Spot(p.slot, y - p.top, x)
        last = self.places[-1]
        return Spot(last.slot, max(last.height - 1, 0), x)

    def drag(self, x: int, y: int) -> None:
        self._dragging = True
        if y <= 0 or y >= self.rows - 1:  # at the edge: carry on in that direction
            self.scroll(-1 if y <= 0 else 1)
            self.places = self.doc.window(*self.top(), self.rows, self.cols).places
        if self._press_spot is not None and (end := self.spot_at(x, y)) is not None:
            self.selection = (self._press_spot, end)

    def ordered(self) -> tuple[tuple[int, Spot], tuple[int, Spot]] | None:
        """The selection as (index of slot, spot) from the earlier end to the later, or None if it is gone."""
        if self.selection is None:
            return None
        ends = [(self.doc._index(s.slot), s) for s in self.selection]
        if any(i is None for i, _ in ends):
            self.selection = None
            return None
        return tuple(sorted(ends, key=lambda e: (e[0], e[1].row, e[1].col)))  # type: ignore[return-value]

    def span(self, ordered, index: int, row: int) -> tuple[int, int | None] | None:
        """Which cells of this row are selected: (first, one past the last or None for the end of the row), or None."""
        (i, a), (j, b) = ordered
        if not (i, a.row) <= (index, row) <= (j, b.row):
            return None
        first = a.col if (index, row) == (i, a.row) else 0
        last = b.col + 1 if (index, row) == (j, b.row) else None
        return first, last

    def selected_text(self) -> str:
        """What the selection covers as text: no colours, rows that were cut from one long line joined back, box frames left out."""
        ordered = self.ordered()
        if ordered is None:
            return ""
        out = ""
        for index in range(ordered[0][0], ordered[1][0] + 1):
            slot = self.doc.slots[index]
            rows, joined = self.doc.rows_for(slot, self.cols), self.doc.joined_for(slot, self.cols)
            drawn = bool(slot.box.hooks.layout) and slot.box.framed
            for r, row in enumerate(rows):
                if (cells := self.span(ordered, index, r)) is None:
                    continue
                piece = cut(strip(row), *cells)
                if drawn:
                    piece = unbox(piece.rstrip())
                if out and joined[r]:
                    out += piece  # the rest of a line that was cut to fit the screen: keep the space it was cut at
                else:
                    out = (out.rstrip(" ") + "\n" if out else "") + piece
        return out.rstrip(" ").strip("\n")

    def highlighted(self, rows: list[str], places: list[Place]) -> list[str]:
        """The rows with the selection in reverse video."""
        ordered = self.ordered()
        if ordered is None:
            return rows
        rows = list(rows)
        for p in places:
            if (index := self.doc._index(p.slot)) is None or not ordered[0][0] <= index <= ordered[1][0]:
                continue
            for r in range(p.height):
                if 0 <= (y := p.top + r) < len(rows) and (cells := self.span(ordered, index, r)) is not None:
                    rows[y] = highlight(rows[y], *cells)
        return rows

    def own_keys(self, raw: bytes) -> Outcome:
        """The keys this panel uses itself: it scrolls, and lets go of a selection."""
        if raw in UP:
            self.scroll(-1)
        elif raw in DOWN:
            self.scroll(1)
        elif raw in PAGE_UP:
            self.scroll(-(self.rows - 1))
        elif raw in PAGE_DOWN:
            self.scroll(self.rows - 1)
        elif raw in HOME:
            self.anchor, self.offset, self.follow = (self.doc.slots[0] if self.doc.slots else None), 0, False
        elif raw in END:
            self.follow = True
        elif raw == b"\x1b":  # escape lets go of a selection
            self.selection = None
        else:
            return Outcome.PASS
        return Outcome.HANDLED

    def to_input(self, raw: bytes) -> Redirect | Outcome:
        """Any other key is typing: it goes to the input bar, and focus goes with it, so only the first key is ever forwarded."""
        return Redirect("input", raw) if self.panes.known("input") else Outcome.PASS

    def on_key(self, ev: Key) -> bool:
        """Returns False to quit."""
        raw = ev.raw
        if self.focus is not None:  # a box has the keyboard: all of it, but the way out
            if raw == LEAVE:
                self.set_focus(None)
            else:
                self.hook(self.focus.box, "on_key", raw)
            return True
        decision = route(raw, self.own_keys, self.to_input)
        if isinstance(decision, Redirect):
            self.panes.apply(decision)
        elif decision is Outcome.PASS and raw == QUIT:  # on its own, with no input bar to pass it to, ctrl-c ends it
            return False
        return True

    # --- drawing ---

    def frame(self) -> tuple[list[str], tuple[int, int] | None]:
        anchor, offset = self.top()
        win = self.doc.window(anchor, offset, self.rows, self.cols)
        self.places = win.places
        cursor = None
        if self.focus is not None and self.focus.box is not None:
            if at := self.hook(self.focus.box, "cursor"):
                for p in win.places:
                    if p.slot is self.focus and 0 <= (y := p.top + at[1]) < self.rows:
                        cursor = (at[0], y)
        return self.highlighted(win.rows, win.places), cursor

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        self._poke = asyncio.Event()
        readers = [*self.screen.fds(), self._wake_r]
        for fd in readers:
            loop.add_reader(fd, self._poke.set)
        following = asyncio.create_task(self._follow())
        try:
            while await self._step():
                pass
        finally:
            for fd in readers:
                loop.remove_reader(fd)
            following.cancel()
            await asyncio.gather(following, return_exceptions=True)
            self.doc.close()
            self.host.close()
            os.close(self._wake_r)
            os.close(self._wake_w)

    async def _follow(self) -> None:
        async with aclosing(self.log.changes()) as changes:
            async for snapshot in changes:
                self.snapshot = snapshot
                self._poke.set()

    async def _step(self) -> bool:
        """Wait for something to happen, then draw what it changed. False to quit."""
        await self._poke.wait()
        self._poke.clear()
        try:
            os.read(self._wake_r, 4096)
        except BlockingIOError:
            pass
        for ev in self.screen.read():
            if isinstance(ev, Mouse):
                self.on_mouse(ev)
            elif not self.on_key(ev):
                return False
            self.dirty = True
        snapshot, self.snapshot = self.snapshot, None
        if snapshot is not None and self.doc.sync(snapshot):
            self.dirty = True
        if self.doc.replace_failed():
            self.dirty = True
        self.grant_focus()
        if self.focus is not None and (
            self.focus not in self.doc.slots or self.focus.box is None or not self.focusable(self.focus.box)
        ):
            self.set_focus(None)  # it was replaced, or its program ended: the keyboard is ours again
            self.dirty = True
        if self.screen.resized or self.screen.size() != (self.cols, self.rows):
            self.screen.resized = False
            self.cols, self.rows = self.screen.size()
            self.screen.invalidate()
            self.dirty = True
        if self.dirty:
            self.dirty = False
            self.screen.draw(*self.frame())
        return True
