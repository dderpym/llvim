"""std/cues.py: cues, messages that ask whoever listens on a channel to act: sending one, receiving one, and waiting for the
turn they make up to be over."""

from collections.abc import AsyncIterator
from contextlib import aclosing

from llvim.core import Log, Request, Snapshot, Writer
from llvim.std.conversation import Entry, Tag, decode, encode

GENERATE = "generate"  # a model should write the next message


def channel(entry: Entry) -> str | None:
    """The channel of a cue, or None if the entry is not one."""
    tags = entry.tags
    return tags[1] if len(tags) == 2 and tags[0] == Tag.CUE and isinstance(tags[1], str) else None


def is_cue(entry: Entry, on: str | None = None) -> bool:
    """A cue; with `on`, a cue on that channel."""
    found = channel(entry)
    return found is not None and (on is None or found == on)


def cued(snapshot: Snapshot) -> str | None:
    """The channel of the cue that is still wanted: the last message, if it is a cue."""
    return channel(decode(snapshot.messages[-1])) if snapshot.messages else None


def send(writer: Writer, on: str) -> int:
    """Cue `on` after what the writer has written. It is sent with the writer's next commit."""
    return writer.append(encode([Tag.CUE, on]))


async def take(log: Log, on: str, request: Request) -> Writer | None:
    """The log, claimed with `request`, if `on` is cued now and still is once it is held; else None, and nothing held."""
    if cued(log.read()) != on:
        return None
    writer = await log.claim(request)
    if cued(log.read()) == on:
        return writer
    writer.release()
    return None


async def receive(log: Log, on: str, request: Request) -> AsyncIterator[Writer]:
    """Each time `on` is cued, the log, claimed and still cued. It is released when the loop body is done with it."""
    async with aclosing(log.changes()) as changes:
        async for snapshot in changes:
            if cued(snapshot) == on and (writer := await take(log, on, request)) is not None:
                async with writer:
                    yield writer


def busy(log: Log) -> bool:
    """The turn is not over: somebody holds the log, or a cue waits for its listener."""
    return log.holder() is not None or cued(log.read()) is not None


async def take_turn(log: Log, request: Request) -> Writer:
    """The log, claimed with `request` once the whole turn in progress is over, and with no cue left once it is held."""
    while True:
        async with aclosing(log.changes()) as changes:
            async for _ in changes:
                if not busy(log):
                    break
        writer = await log.claim(request)
        if cued(log.read()) is None:
            return writer
        writer.release()
