"""std/tools/bash/terminal.py: run, a command in a hidden tmux window tagged with its call, so a viewer can find it and show it.
A command nobody types into writes to a file, which is what it returns; an interactive one returns the screen."""

from __future__ import annotations

import asyncio
import contextlib
import os
import shlex
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from llvim.std.tmux import Control, Embedded

CALL_OPTION = "@llvim_call"  # the pane option that says which tool call a terminal is running
COLUMNS, ROWS = 100, 14  # until a viewer sizes it to its box
GRACE = 3.0  # seconds a command gets to stop after ctrl-c before its terminal is closed on it
FRAME = 0.05  # seconds between looks at whether it has exited


@dataclass(frozen=True)
class Ran:
    output: str  # the bytes it wrote, as text; for an interactive command, the screen
    status: int | None  # None if it was stopped
    timed_out: bool = False
    cancelled: bool = False


_connection: list[Control] = []


def control() -> Control:
    """The one tmux connection, made when first needed and again if it has closed. Raises TmuxError outside tmux."""
    if not _connection or _connection[0].closed:
        _connection[:] = [Control.here()]
    return _connection[0]


def line(command: str, output: Path | None) -> str:
    """The shell line that runs `command`, with no pager, so nothing waits for a key. With `output` (not interactive): no input,
    stdout and stderr appended to that file, and `tail` showing the file in the pane until the line's shell exits."""
    run = f"PAGER=cat GIT_PAGER=cat bash -c {shlex.quote(command)}"
    if output is None:
        return run
    file = shlex.quote(str(output))
    return f"tail -s 0.05 -f -n +1 --pid=$$ {file} & {run} </dev/null >>{file} 2>&1"


async def run(
    command: str, cwd: Path, call_id: str, timeout: float, interactive: bool, tmux: Control | None = None
) -> Ran:
    """Run `command` and wait for it to exit. Past `timeout`, or cancelled, it gets ctrl-c, then its terminal is closed on it if it
    ignores that. Cancelled, it still returns, with what it had printed: the caller wants that more than the cancel."""
    output = None if interactive else _new_file()
    try:
        term = Embedded.start(tmux or control(), line(command, output), str(cwd), COLUMNS, ROWS, {CALL_OPTION: call_id})
        try:
            deadline = time.monotonic() + timeout
            try:
                while not (shot := term.snapshot()).dead and time.monotonic() < deadline:
                    await asyncio.sleep(FRAME)
            except asyncio.CancelledError:
                await stop(term)
                return Ran(_read(term, output), None, cancelled=True)
            if shot.dead:
                return Ran(_read(term, output), shot.status)
            await stop(term)
            return Ran(_read(term, output), None, timed_out=True)
        finally:
            term.close()
    finally:
        if output is not None:
            with contextlib.suppress(FileNotFoundError):
                output.unlink()


def _new_file() -> Path:
    """An empty file only its owner can read: the output may hold secrets."""
    fd, path = tempfile.mkstemp(prefix="llvim-bash-", suffix=".out")
    os.close(fd)
    return Path(path)


def _read(term: Embedded, output: Path | None) -> str:
    if output is not None:
        return output.read_bytes().decode(errors="replace")
    return screen(term.transcript())


def screen(transcript: str) -> str:
    """The transcript without the empty rows under the last line, which are the terminal's, not the program's."""
    return transcript.rstrip("\n")


async def stop(term: Embedded) -> None:
    """Ctrl-c, and wait up to GRACE for it to exit. Closing the terminal afterwards ends it either way."""
    term.interrupt()
    deadline = time.monotonic() + GRACE
    while not term.snapshot().dead and time.monotonic() < deadline:
        await asyncio.sleep(FRAME)
