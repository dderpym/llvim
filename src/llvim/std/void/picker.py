"""std/void/picker.py: Picker, the list of a log's turns where you void messages and put them back, with the log held while
it is open, and `llvim-void`, its command."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from dataclasses import dataclass
from typing import Any

from llvim.core import Author, Log, Request, Writer
from llvim.std.conversation import Entry, entries
from llvim.std.panels.keys import DOWN, UP, Key
from llvim.std.panels.logviewer.ansi import RESET, cut, pad, width
from llvim.std.void.tag import marked
from llvim.std.void.turns import Element, Turn, Voided, turns

ENTER, TOGGLE, OPEN, SHUT, CLOSE = (b"\r", b"\n"), (b"v", b" "), (b"\t", b"\x1b[C", b"\x1bOC"), (b"\x1b[D", b"\x1bOD"), (b"\x1b", b"q", b"\x03")  # fmt: skip
SHOW = (b"a",)
HELP = "enter: void from here on · v: void or restore · tab: open a turn · a: {} voided · esc: close"
WAITING = "waiting for the log: it is in use (esc gives up)"
REQUEST = Request(0, "/void")  # what the others see holds the log while the picker is open
SELECTED, DIM, HEAD = "\x1b[7m", "\x1b[2m", "\x1b[1m"
MARK = {Voided.NONE: "", Voided.PART: "◐", Voided.ALL: "VOID"}


@dataclass(frozen=True)
class Row:
    turn: Turn
    number: int  # of the turn, from 1
    element: Element | None = None  # None: the row of the turn itself

    @property
    def id(self) -> tuple[int, int | None]:
        return self.turn.id, self.element.id if self.element else None

    @property
    def entries(self) -> tuple[Entry, ...]:
        return self.element.entries if self.element else self.turn.entries

    @property
    def voided(self) -> Voided:
        return (self.element or self.turn).voided


async def set_void(writer: Writer, log: Log, ids: list[int], void: bool) -> None:
    """Put the void tag on these messages (or take it off) and commit, as the user."""
    now = {message.id: message.content for message in log.read().messages}
    for id in ids:
        if id in now and (changed := marked(now[id], void)) is not None:
            writer.replace(id, changed)
    await writer.commit(author=Author(getpass.getuser()), message="void" if void else "restore")


class Picker:
    """`writer` is the log, held: nothing else writes while the picker is open, so the list cannot go stale."""

    def __init__(self, log: Log, screen: Any, writer: Writer):
        self.log, self.screen, self.writer = log, screen, writer
        self.turns: list[Turn] = []
        self.open: set[int] = set()  # the turns shown with their elements, by id
        self.at: tuple[int, int | None] | None = None  # the chosen row's id; None before there is one
        self.show_voided = False
        self.notice, self.done = "", False
        self._poke = asyncio.Event()
        self.load()

    def load(self, near: int | None = None) -> None:
        """Read the log. The chosen row stays chosen; at first, the last turn is."""
        self.turns = turns(entries(self.log.read()))
        self._keep_choice(near)

    def _keep_choice(self, near: int | None) -> None:
        """If the chosen row is no longer shown, choose the one now at its place, `near`."""
        rows = self.rows()
        if not rows or self.at in {row.id for row in rows}:
            return
        if near is None:
            self.at = next(row.id for row in reversed(rows) if row.element is None)
        else:
            self.at = rows[min(near, len(rows) - 1)].id

    def rows(self) -> list[Row]:
        out = []
        for number, turn in enumerate(self.turns, 1):
            if self._shown(turn):
                out.append(Row(turn, number))
                if turn.id in self.open:
                    out.extend(Row(turn, number, element) for element in turn.elements if self._shown(element))
        return out

    def _shown(self, part: Turn | Element) -> bool:
        return self.show_voided or part.voided != Voided.ALL

    def _index(self) -> int | None:
        return next((i for i, row in enumerate(self.rows()) if row.id == self.at), None)

    def chosen(self) -> Row | None:
        return next((row for row in self.rows() if row.id == self.at), None)

    async def on_key(self, raw: bytes) -> None:
        self.notice = ""
        row = self.chosen()
        if raw in CLOSE:
            self.done = True
        elif raw in SHOW:
            near = self._index()
            self.show_voided = not self.show_voided
            self._keep_choice(near)
        elif row is None:
            return
        elif raw in UP or raw == b"k":
            self.move(-1)
        elif raw in DOWN or raw == b"j":
            self.move(1)
        elif raw in OPEN:
            self.open.add(row.turn.id)
        elif raw in SHUT:
            self.open.discard(row.turn.id)
            self.at = (row.turn.id, None)
        elif raw in TOGGLE:
            await self.mark([entry.id for entry in row.entries], void=row.voided != Voided.ALL)
        elif raw in ENTER:
            first = row.entries[0].id
            await self.mark([entry.id for turn in self.turns for entry in turn.entries if entry.id >= first], void=True)
            self.done = True

    def move(self, by: int) -> None:
        rows = self.rows()
        index = next(i for i, row in enumerate(rows) if row.id == self.at)
        self.at = rows[max(0, min(len(rows) - 1, index + by))].id

    async def mark(self, ids: list[int], void: bool) -> None:
        near = self._index()
        await set_void(self.writer, self.log, ids, void)
        self.load(near)

    def render(self, cols: int, height: int) -> list[str]:
        """The screen: a line of help (or the notice), then as many rows as fit, scrolled to keep the chosen one in sight."""
        rows = self.rows()
        room = max(height - 1, 1)
        index = self._index() or 0
        top = max(0, min(index - room // 2, len(rows) - room))
        body = [self._line(row, cols, row.id == self.at) for row in rows[top : top + room]]
        help = HELP.format("hide" if self.show_voided else "show")
        empty = "all of it is voided (a: show it)" if self.turns else "the log is empty"
        return [
            pad(cut(f"{HEAD}{self.notice or help}{RESET}", 0, cols), cols),
            *(body or [pad(f"{DIM}{empty}{RESET}", cols)]),
        ]

    def _line(self, row: Row, cols: int, selected: bool) -> str:
        if row.element is None:
            arrow = "▾" if row.turn.id in self.open else "▸"
            text = f" {arrow} {row.number:>3}  {row.turn.label}"
        else:
            text = f"          {row.element.label}"
        mark = MARK[row.voided]
        text = pad(cut(text, 0, max(cols - width(mark) - 2, 1)), max(cols - width(mark) - 1, 1)) + mark + " "
        style = SELECTED if selected else DIM if row.voided == Voided.ALL else ""
        return f"{style}{pad(text, cols)}{RESET}"

    def draw(self) -> None:
        cols, height = self.screen.size()
        self.screen.draw(self.render(cols, height))

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        fds = self.screen.fds()
        for fd in fds:
            loop.add_reader(fd, self._poke.set)
        try:
            while not self.done:
                self.draw()
                await self._poke.wait()
                self._poke.clear()
                try:
                    events = self.screen.read()
                except EOFError:
                    return
                for event in events:
                    if isinstance(event, Key) and not self.done:
                        await self.on_key(event.raw)
        finally:
            for fd in fds:
                loop.remove_reader(fd)


async def pick(log: Log, screen: Any, address: str | None = None) -> None:
    """Show the picker with the log held until it closes. With `address`, the claim offered there is adopted (`/void` waited
    for it, and hands it over). Without, the log is claimed here: while that waits a line says so, and a closing key gives up."""
    writer = await log.adopt(address) if address else await _claim(log, screen)
    if writer is not None:
        async with writer:
            await Picker(log, screen, writer).run()


async def _claim(log: Log, screen: Any) -> Writer | None:
    loop = asyncio.get_running_loop()
    poke = asyncio.Event()
    fds = screen.fds()
    claiming = asyncio.ensure_future(log.claim(REQUEST))
    claiming.add_done_callback(lambda _: poke.set())
    for fd in fds:
        loop.add_reader(fd, poke.set)
    try:
        while not claiming.done():
            cols, _ = screen.size()
            screen.draw([pad(cut(f"{HEAD}{WAITING}{RESET}", 0, cols), cols)])
            await poke.wait()
            poke.clear()
            try:
                gave_up = any(isinstance(event, Key) and event.raw in CLOSE for event in screen.read())
            except EOFError:
                gave_up = True
            if gave_up:
                return None
        return claiming.result()
    finally:
        for fd in fds:
            loop.remove_reader(fd)
        if not claiming.done():
            claiming.cancel()
            await asyncio.gather(claiming, return_exceptions=True)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="llvim-void", description="Void messages of a log, and put them back.")
    ap.add_argument("log", nargs="?", default="main")
    ap.add_argument("-p", "--project", default=".", help="project folder (default: the working folder)")
    ap.add_argument("--adopt", metavar="ADDRESS", help="take over the claim offered there, instead of claiming the log")
    args = ap.parse_args(argv)
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        sys.exit("llvim-void needs a terminal")
    from llvim.std.panels.logviewer.screen import Screen

    with Screen(mouse=False) as screen:
        try:
            asyncio.run(pick(Log(args.project, args.log), screen, args.adopt))
        except KeyboardInterrupt:
            pass
