"""std/cues.py: a cue, a message that asks whoever listens on its channel to act, and when one is still wanted."""

from llvim.core import Log, Snapshot
from llvim.std.conversation import Entry, Tag, decode, encode

GENERATE = "generate"  # a model should write the next message


def cue(channel: str) -> bytes:
    return encode([Tag.CUE, channel])


def channel(entry: Entry) -> str | None:
    """The channel of a cue, or None if the entry is not one."""
    tags = entry.tags
    return tags[1] if len(tags) == 2 and tags[0] == Tag.CUE and isinstance(tags[1], str) else None


def cued(snapshot: Snapshot) -> str | None:
    """The channel of the cue that is still wanted: the last message, if it is a cue."""
    return channel(decode(snapshot.messages[-1])) if snapshot.messages else None


def busy(log: Log) -> bool:
    """The turn is not over: somebody holds the log, or a cue waits for its listener."""
    return log.holder() is not None or cued(log.read()) is not None
