"""std/tools/bash/command.py: COMMAND, `/bash [command]` in the input bar: a terminal in the log that you type into."""

from __future__ import annotations

import json
import uuid

from llvim.core import Log, Writer
from llvim.std.conversation import Field
from llvim.std.cues import TOOLS, send
from llvim.std.panels.input.bar import after_turn
from llvim.std.panels.input.commands import Command, Context
from llvim.std.panels.keys import Panes, Redirect
from llvim.std.tools.calls import call


def user_call(command_line: str) -> bytes:
    """A bash call of the user's: interactive, since they will type into it, and a shell when no command is given."""
    arguments = json.dumps({"command": command_line or "bash", "interactive": True})
    return call("bash", arguments, f"user_{uuid.uuid4().hex[:12]}", **{Field.USER: True})


async def open_terminal(log: Log, command_line: str, panes: Panes | None) -> None:
    def write(writer: Writer) -> None:
        writer.append(user_call(command_line))
        send(writer, TOOLS)

    await after_turn(log, write, message="/bash")
    if panes is not None:  # the box takes the keyboard once its terminal is up; this brings the keyboard to the viewer
        panes.apply(Redirect("viewer"))


def run(ctx: Context, arg: str) -> None:
    if ctx.queue is None:
        ctx.notice("/bash needs the input bar's queue")
        return
    ctx.queue("/bash", lambda log: open_terminal(log, arg, ctx.panes))


COMMAND = Command("bash", "open a terminal in the log (or run a command in it)", run)
