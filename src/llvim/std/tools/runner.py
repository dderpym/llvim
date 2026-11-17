"""std/tools/runner.py: Runner, the program that answers the tool calls a provider left in the log (`llvim-tools`)."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Iterable

from llvim.core import Author, Log, Request, Writer
from llvim.std import env
from llvim.std.conversation import Entry, Field, Info, Tag, encode, entries
from llvim.std.cues import GENERATE, TOOLS, receive, send, take
from llvim.std.tools.calls import RESULT, START, answer, by_user, call_id, cut_off, name, pending
from llvim.std.tools.registry import Context, Registry, Result, Tool

AUTHOR = Author("llvim-tools")
REQUEST = Request(0, {Info.TOOLS: "llvim-tools"})
CUT_OFF = "[interrupted: the tool runner stopped while this call ran, so it was not run again]"
STOPPED = "[interrupted]"
NOTHING = "the tools were cued, but no call is waiting for a result"


async def run_calls(log: Log, writer: Writer, registry: Registry) -> int:
    """Answer the waiting calls, the log held: those a runner was cut off running as interrupted, the rest by running them, oldest
    first. Returns how many were answered. Outranked while one runs, it answers that one and leaves the rest. The model is cued
    after the last result if any of its calls were waiting."""
    now = entries(log.read())
    cut, waiting = cut_off(now), pending(now)
    cut_ids = {call_id(c) for c in cut}
    to_run = [c for c in waiting if call_id(c) not in cut_ids]
    model_waits = any(not by_user(c) for c in waiting)
    if not cut and not to_run:
        writer.append(
            encode([Tag.ERROR], NOTHING)
        )  # overtakes the cue, which would otherwise keep the turn going forever
        await writer.commit(author=AUTHOR)
        return 0
    for call in cut:
        writer.append(answer(RESULT, call, CUT_OFF, **{Field.ERROR: True}))
    for call in to_run:
        writer.append(answer(START, call))
        await writer.commit(author=AUTHOR)  # before it runs: a call that is cut off is never run twice
        result, outranked = await run_call(log, writer, registry, call)
        writer.append(answer(RESULT, call, result.text, **{Field.ERROR: result.error}))
        if outranked:
            await writer.commit(author=AUTHOR)
            return len(cut) + to_run.index(call) + 1
    if model_waits:
        send(writer, GENERATE)
    await writer.commit(author=AUTHOR)
    return len(cut) + len(to_run)


async def run_call(log: Log, writer: Writer, registry: Registry, call: Entry) -> tuple[Result, bool]:
    """Run one call, racing it against someone outranking the writer. The second value: it was outranked, and the tool cancelled."""
    ctx = Context(log.project, call, log, writer)
    running = asyncio.ensure_future(registry.run(name(call), call.content, ctx))
    outranked = asyncio.ensure_future(_until_outranked(writer))
    try:
        await asyncio.wait({running, outranked}, return_when=asyncio.FIRST_COMPLETED)
        if running.done():
            return running.result(), False
        running.cancel()
        try:
            return await running, True
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling():
                raise
            return Result(STOPPED, error=True), True  # the tool did not say what it had done
    finally:
        for task in (running, outranked):
            task.cancel()
        await asyncio.gather(running, outranked, return_exceptions=True)


async def _until_outranked(writer: Writer) -> None:
    while True:
        await writer.outranked_changed()
        if writer.outranked():
            return


async def recover(log: Log, registry: Registry) -> int:
    """Answer the calls a dead runner left cut off, if there are any; then the rest of their turn."""
    if not cut_off(entries(log.read())):
        return 0
    async with await log.claim(REQUEST) as writer:
        if not cut_off(entries(log.read())):  # another runner did it while this one waited
            return 0
        return await run_calls(log, writer, registry)


async def respond(log: Log, registry: Registry) -> int:
    """Answer the calls if the tools are cued now. Returns how many were answered."""
    writer = await take(log, TOOLS, REQUEST)
    if writer is None:
        return 0
    async with writer:
        return await run_calls(log, writer, registry)


async def serve(log: Log, registry: Registry) -> None:
    """Answer each cue for the tools, until cancelled."""
    await recover(log, registry)
    async for writer in receive(log, TOOLS, REQUEST):
        await run_calls(log, writer, registry)


class Runner:
    """The runner as a program: `Runner(tools=[...]).run()` answers the calls it is cued for until interrupted. `log` defaults to
    the session's (`env.log`); tools run in its project folder."""

    def __init__(self, tools: Iterable[Tool] = (), log: Log | None = None, once: bool = False):
        self.registry, self.log, self.once = Registry(tools), log, once

    def run(self) -> None:
        log = self.log or env.log()
        work = respond(log, self.registry) if self.once else serve(log, self.registry)
        try:
            asyncio.run(work)
        except KeyboardInterrupt:
            pass


def main(argv: list[str] | None = None) -> None:
    from llvim.std.tools import bash

    ap = argparse.ArgumentParser(prog="llvim-tools", description="Run the tool calls a provider left in a log.")
    ap.add_argument("log", nargs="?", default="main")
    ap.add_argument(
        "-p", "--project", default=".", help="project folder, where tools run (default: the working folder)"
    )
    ap.add_argument("--once", action="store_true", help="answer the calls if the tools are cued now, then exit")
    args = ap.parse_args(argv)
    Runner([bash.TOOL], Log(args.project, args.log), args.once).run()
