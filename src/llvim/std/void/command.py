"""std/void/command.py: COMMAND, `/void` in the input bar: the picker, in a tmux popup over the session."""

from __future__ import annotations

import asyncio
import os
import shlex
from collections.abc import Callable

from llvim.core import Log
from llvim.std.cues import take_turn
from llvim.std.panels.input.commands import Command, Context
from llvim.std.void.picker import REQUEST

START_TIMEOUT = 10.0  # seconds a picker has to start and take the claim, before the log is let go
PASSED_ON = ("PATH", "LLVIM_STORE", "LLVIM_HOME")  # a popup starts from tmux's environment, not the bar's


def popup(log: Log, address: str, client: str | None = None) -> list[str]:
    """The tmux command that shows the picker for `log` in a popup, which closes when the picker does. The picker adopts the
    claim offered at `address`."""
    env = [f"{name}={os.environ[name]}" for name in PASSED_ON if os.environ.get(name)]
    picker = shlex.join(["env", *env, "llvim-void", log.name, "-p", str(log.project), "--adopt", address])
    on = ["-c", client] if client else []
    return ["tmux", "display-popup", "-E", *on, "-w", "80%", "-h", "80%", "-d", str(log.project), picker]


async def terminal_client() -> str | None:
    """The client of this session that a person looks at. The viewer and the tool runner are clients of it too, in control mode,
    and a popup sent to one of those shows nowhere."""
    session = ["-t", pane] if (pane := os.environ.get("TMUX_PANE")) else []
    listing = await asyncio.create_subprocess_exec(
        "tmux", "list-clients", *session, "-F", "#{client_control_mode} #{client_name}",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )  # fmt: skip
    out, _ = await listing.communicate()
    clients = (line.partition(" ") for line in out.decode().splitlines())
    return next((name for control_mode, _, name in clients if control_mode == "0"), None)


async def show(log: Log, notice: Callable[[str], None]) -> None:
    """Claim the log once the turn in progress is over, then show the picker in a popup and hand it the claim. The claim is
    made here so that it waits in the log's queue like a message; the picker is another process, so it is handed over."""
    async with await take_turn(log, REQUEST) as writer:
        offer = writer.offer()
        shown = await asyncio.create_subprocess_exec(
            *popup(log, offer.address, await terminal_client()),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        taken, closed = asyncio.ensure_future(offer.taken(START_TIMEOUT)), asyncio.ensure_future(shown.communicate())
        await asyncio.wait({taken, closed}, return_when=asyncio.FIRST_COMPLETED)
        if not taken.done():  # the popup ended without a picker ever asking for the claim
            taken.cancel()
        _, error = await closed
        problem = (await asyncio.gather(taken, return_exceptions=True))[0]
    if isinstance(problem, BaseException) or shown.returncode:
        notice(f"/void: {error.decode(errors='replace').strip() or 'the picker did not start'}")


def open_picker(ctx: Context, arg: str) -> None:
    if not os.environ.get("TMUX"):
        ctx.notice("/void opens in a tmux popup, and this is not in tmux")
    elif ctx.queue is None:
        ctx.notice("/void needs the input bar's queue")
    else:
        ctx.queue("/void", lambda log: show(log, ctx.notice))


COMMAND = Command("void", "take messages out of the conversation, or put them back", open_picker)
