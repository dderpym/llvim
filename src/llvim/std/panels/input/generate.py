"""std/panels/input/generate.py: `/continue`, which asks the model to go on from the log as it is."""

from llvim.core import Log, Writer
from llvim.std.cues import GENERATE, send
from llvim.std.panels.input.bar import after_turn
from llvim.std.panels.input.commands import Command, Context


async def cue_the_model(log: Log) -> None:
    def write(writer: Writer) -> None:
        send(writer, GENERATE)

    await after_turn(log, write, message="continue")


def go_on(ctx: Context, arg: str) -> None:
    if not ctx.log.read().messages:
        ctx.notice("nothing to continue: the log is empty")
    elif ctx.queue is None:
        ctx.notice("/continue needs the input bar's queue")
    else:
        ctx.queue("/continue", cue_the_model)


CONTINUE = Command("continue", "have the model go on, without a new message", go_on)
