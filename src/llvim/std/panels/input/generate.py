"""std/panels/input/generate.py: `/continue`, which asks the model to go on from the log as it is."""

import getpass

from llvim.core import Author, Request
from llvim.std.conversation import Info
from llvim.std.cues import GENERATE, cue, cued
from llvim.std.panels.input.bar import PRIORITY
from llvim.std.panels.input.commands import Command, Context


async def go_on(ctx: Context, arg: str) -> None:
    try:
        writer = await ctx.log.claim(Request(PRIORITY, {Info.INPUT: "continue"}), timeout=0)
    except TimeoutError:
        ctx.notice("busy: the model is replying (or something is writing the log)")
        return
    async with writer:
        snapshot = ctx.log.read()
        if not snapshot.messages:
            ctx.notice("nothing to continue: the log is empty")
        elif cued(snapshot) is None:
            writer.append(cue(GENERATE))
            await writer.commit(author=Author(getpass.getuser()), message="continue")


CONTINUE = Command("continue", "have the model go on, without a new message", go_on)
