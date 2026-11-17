"""std/panels/status/bar.py: State, what a status renderer is given, and StatusBar, which updates the renderers and puts
their pieces in one line."""

import asyncio
import time
from collections.abc import Callable, Sequence
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any

from llvim.core import Log, Request, Snapshot
from llvim.std.context import ContextRenderer
from llvim.std.context import render as render_context
from llvim.std.conversation import Entry, Field, decode, entries
from llvim.std.cues import is_cue
from llvim.std.panels.keys import Key, Panes, Redirect
from llvim.std.panels.logviewer.ansi import pad, width, wrap

SEPARATOR = " \x1b[38;5;240m·\x1b[0m "
TICK = 1.0  # seconds between redraws while the turn runs: the clock shows whole seconds


@dataclass(frozen=True)
class State:
    snapshot: Snapshot
    last: Entry | None  # the last message of the conversation: of the log as the context renderers leave it
    holder: Request | None
    model: str | None  # the model of the last message that names one
    busy_since: float | None  # when the turn in progress began, on `now`'s clock; None when it is over
    now: float


type StatusRenderer = Callable[[State], str | None]


def compose(pieces: Sequence[str | None], cols: int) -> str:
    """The pieces that are not empty, in order, joined and fitted to the width."""
    line = SEPARATOR.join(" " + piece if i == 0 else piece for i, piece in enumerate(p for p in pieces if p))
    return pad(line if width(line) <= cols else wrap(line, max(cols - 1, 1))[0] + "…", cols)


def last_model(snapshot: Snapshot) -> str | None:
    for message in reversed(snapshot.messages):
        if name := decode(message).extra.get(Field.MODEL):
            return str(name)
    return None


class StatusBar:
    def __init__(self, log: Log, screen: Any, renderers: Sequence[StatusRenderer], panes: Panes | None = None,
                 clock: Callable[[], float] = time.monotonic, context: Sequence[ContextRenderer] = ()):  # fmt: skip
        self.log, self.screen, self.renderers, self.panes, self.clock = (
            log,
            screen,
            list(renderers),
            panes or Panes(),
            clock,
        )
        self.context = list(context)
        self._last: tuple[Snapshot, Entry | None] | None = None
        self.busy_since: float | None = None
        self._snapshot: Snapshot | None = None
        self._model: tuple[Snapshot, str | None] | None = None

    def state(self, snapshot: Snapshot) -> State:
        entry = self._last_entry(snapshot)
        holder, now = self.log.holder(), self.clock()
        busy = holder is not None or (entry is not None and is_cue(entry))
        if not busy:
            self.busy_since = None
        elif self.busy_since is None:
            self.busy_since = now
        if self._model is None or self._model[0] is not snapshot:
            self._model = (snapshot, last_model(snapshot))
        return State(snapshot, entry, holder, self._model[1], self.busy_since, now)

    def _last_entry(self, snapshot: Snapshot) -> Entry | None:
        uncommitted = {m.id for m in snapshot.uncommitted}
        last = snapshot.messages[-1] if snapshot.messages else None
        if last is None:
            return None
        if last.id in uncommitted or not self.context:
            # A message being written is what is happening, whatever a renderer makes of it, and it changes with every chunk:
            # the whole log is not read for each.
            return decode(last, last.id in uncommitted, last.id in uncommitted)
        if self._last is None or self._last[0] is not snapshot:
            conversation = render_context(entries(snapshot), self.context)
            self._last = (snapshot, conversation[-1] if conversation else None)
        return self._last[1]

    def line(self, snapshot: Snapshot, cols: int) -> str:
        """Each renderer updated with the state now, and their pieces in one line. A renderer that raises shows nothing."""
        state = self.state(snapshot)
        pieces = []
        for render in self.renderers:
            try:
                pieces.append(render(state))
            except Exception:
                pieces.append(None)
        return compose(pieces, cols)

    def on_key(self, raw: bytes) -> None:
        """The status bar does not type: a key goes to the input bar, and the focus with it."""
        self.panes.apply(Redirect("input", raw))

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        poke = asyncio.Event()
        fds = self.screen.fds()
        for fd in fds:
            loop.add_reader(fd, poke.set)
        following = asyncio.create_task(self._follow(poke))
        try:
            while True:
                if self._snapshot is not None:
                    cols, _ = self.screen.size()
                    self.screen.draw([self.line(self._snapshot, cols)])
                try:
                    await asyncio.wait_for(poke.wait(), TICK if self.busy_since is not None else None)
                except TimeoutError:
                    pass
                poke.clear()
                try:
                    events = self.screen.read()
                except EOFError:
                    return
                for event in events:
                    if isinstance(event, Key):
                        self.on_key(event.raw)
        finally:
            for fd in fds:
                loop.remove_reader(fd)
            following.cancel()
            await asyncio.gather(following, return_exceptions=True)

    async def _follow(self, poke: asyncio.Event) -> None:
        async with aclosing(self.log.changes()) as changes:
            async for snapshot in changes:
                self._snapshot = snapshot
                poke.set()
