"""std/tools/bash/shared.py: a terminal kept open past the call that started it, which the model and the user take turns at:
start, type, hand_to_user, close."""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from llvim.std.tmux import Control, Embedded, TmuxError
from llvim.std.tools.bash import terminal
from llvim.std.tools.bash.terminal import CALL_OPTION, COLUMNS, FRAME, ROWS

OWNER = "@llvim_owner"  # the pane option that says who may type into a kept terminal, so the viewer's box knows too
AGENT, USER = "agent", "user"


class Closed(LookupError):
    """No kept terminal has that id: it was never started, it exited, it was closed, or its pane is gone."""


@dataclass(frozen=True)
class Seen:
    output: str  # what it printed from the line the cursor was on at the last look (see _look)
    status: int | None = None  # how it exited; None while it runs, or if it had to be killed
    running: bool = True  # False: it has exited or been closed, and its id is no longer kept
    still_changing: bool = False  # the wait ran out before the screen was still
    handed_back: bool = False  # the user handed it back, rather than their time running out
    cancelled: bool = False


class _Kept:
    def __init__(self, term: Embedded):
        self.term = term
        self.given = 0  # the row, counted from the top of history, the next look starts at


_kept: dict[str, _Kept] = {}


async def start(command: str, cwd: Path, id: str, timeout: float, settle: float, tmux: Control | None = None) -> Seen:
    """Run `command` on a terminal kept under `id` (the call's id, which the viewer's box finds it by), and return once its screen
    has been still for `settle` seconds, or at `timeout`. It keeps running either way."""
    options = {CALL_OPTION: id, OWNER: AGENT}
    term = Embedded.start(tmux or terminal.control(), terminal.line(command, None), str(cwd), COLUMNS, ROWS, options)
    _kept[id] = _Kept(term)
    return await _settled(id, timeout, settle)


async def type_keys(id: str, keys: str, timeout: float, settle: float) -> Seen:
    """Type `keys` (a newline is Enter, which a keyboard sends as a carriage return), then wait as `start` does. Empty keys
    only wait."""
    kept = _get(id)
    with _gone_if_tmux_fails(id):
        if keys:
            kept.term.send(keys.replace("\r\n", "\n").replace("\n", "\r").encode())
    return await _settled(id, timeout, settle)


async def hand_to_user(id: str, timeout: float) -> Seen:
    """Let the user type into it, and return once they hand it back (the box sets OWNER back), it exits, or `timeout` runs out.
    It is the model's again however this returns."""
    kept = _get(id)
    deadline = time.monotonic() + timeout
    with _gone_if_tmux_fails(id):
        kept.term.set_option(OWNER, USER)
        try:
            while not (shot := kept.term.snapshot()).dead and _users(kept) and time.monotonic() < deadline:
                await asyncio.sleep(FRAME)
        except asyncio.CancelledError:
            kept.term.set_option(OWNER, AGENT)
            return _look(kept, cancelled=True)
        if shot.dead:
            return _ended(id, shot.status)
        handed_back = not _users(kept)
        kept.term.set_option(OWNER, AGENT)
        return _look(kept, handed_back=handed_back)


async def close(id: str) -> Seen:
    """Stop it as a timed-out command is stopped (ctrl-c, then its terminal is closed on it), and return its last output."""
    kept = _get(id)
    with _gone_if_tmux_fails(id):
        if not kept.term.snapshot().dead:
            await terminal.stop(kept.term)
        return _ended(id, kept.term.snapshot().status)


def is_kept(id: str) -> bool:
    return id in _kept


def close_all() -> None:
    """Close every kept terminal. Run at exit, since a terminal that outlives its program has nobody left to close it."""
    while _kept:
        _kept.popitem()[1].term.close()


atexit.register(close_all)


def _get(id: str) -> _Kept:
    try:
        return _kept[id]
    except KeyError:
        raise Closed(f"there is no open terminal {id!r}: it exited or was closed") from None


@contextlib.contextmanager
def _gone_if_tmux_fails(id: str) -> Iterator[None]:
    """A tmux error on a kept terminal means its pane, or the connection to it, is gone: it is forgotten, and Closed says so."""
    try:
        yield
    except TmuxError as error:
        if (kept := _kept.pop(id, None)) is not None:
            kept.term.close()
        raise Closed(f"terminal {id!r} is gone: {error}") from error


def _users(kept: _Kept) -> bool:
    return kept.term.value(OWNER) == USER


async def _settled(id: str, timeout: float, settle: float) -> Seen:
    kept = _get(id)
    deadline = time.monotonic() + timeout
    last, still_since = None, time.monotonic()
    with _gone_if_tmux_fails(id):
        try:
            while True:
                shot, now = kept.term.snapshot(), time.monotonic()
                if shot.dead:
                    return _ended(id, shot.status)
                if shot != last:
                    last, still_since = shot, now
                elif now - still_since >= settle:
                    return _look(kept)
                if now >= deadline:
                    return _look(kept, still_changing=True)
                await asyncio.sleep(FRAME)
        except asyncio.CancelledError:
            return _look(kept, cancelled=True)


def _look(kept: _Kept, **how) -> Seen:
    """From the row the cursor was on at the last look: a line program does not rewrite what is above it, so the model gets
    what is new and the line it was typing on. A full-screen program (on the alternate screen) redraws anything: the whole screen."""
    term = kept.term
    if term.value("alternate_on") == "1":
        return Seen(terminal.screen(term.transcript(0)), **how)
    history, cursor = int(term.value("history_size")), int(term.value("cursor_y"))
    output = terminal.screen(term.transcript(min(kept.given - history, cursor)))
    kept.given = history + cursor
    return Seen(output, **how)


def _ended(id: str, status: int | None) -> Seen:
    kept = _kept.pop(id)
    try:
        return Seen(_look(kept).output, status, running=False)
    finally:
        kept.term.close()
