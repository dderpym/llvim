"""std/conversation.py: Entry, the message format the standard programs agree on, and the tags they use."""

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from llvim.core import Message, Snapshot


class Tag(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    THINKING = "thinking"  # what the model thought before what it said
    STATUS = "status"  # a note while waiting; always removed before a commit
    ERROR = "error"  # a failure the user should see
    STOP = "stop"  # second tag of the user message that stopped the model
    CUE = "cue"  # `[CUE, channel]`: see cues.py
    TOOL_CALL = "tool_call"  # `[TOOL_CALL, tool]`: see tools/calls.py
    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"


ROLES = (Tag.SYSTEM, Tag.USER, Tag.ASSISTANT)


class Field(StrEnum):
    MODEL = "model"
    CALL_ID = "call_id"  # on a tool call, its start and its result
    USER = "user"  # on a tool call the user made (`/bash`), not the model
    ERROR = "error"  # on a tool result: the call failed


class Info(StrEnum):
    """Keys of the `data` of a claim, which tell the others who holds or waits for the log."""

    PROVIDER = "provider"
    MODEL = "model"
    INPUT = "input"
    TOOLS = "tools"


@dataclass(frozen=True)
class Entry:
    """One message as the standard programs read it."""

    id: int
    tags: list[Any]
    content: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    uncommitted: bool = False
    streaming: bool = False  # uncommitted, and the last message: it may still grow


def encode(tags: list[Any], content: str = "", **extra: Any) -> bytes:
    """A header line of JSON, then the text. `Writer.extend` with more text keeps it valid, which is how a reply streams."""
    header = json.dumps({"tags": list(tags), **extra}, ensure_ascii=False)
    return header.encode() + b"\n" + content.encode()


def decode(message: Message, uncommitted: bool = False, streaming: bool = False) -> Entry:
    """Never fails: a message in no known format is an untagged entry holding its bytes as text."""
    header, newline, body = message.content.partition(b"\n")
    try:
        meta = json.loads(header) if newline else None
    except ValueError:
        meta = None
    if not isinstance(meta, dict) or not isinstance(meta.get("tags"), list):
        return Entry(message.id, [], message.content.decode(errors="replace"), {}, uncommitted, streaming)
    tags = meta.pop("tags")
    return Entry(message.id, tags, body.decode(errors="replace"), meta, uncommitted, streaming)


def entries(snapshot: Snapshot) -> list[Entry]:
    uncommitted = {message.id for message in snapshot.uncommitted}
    last = snapshot.messages[-1].id if snapshot.messages else None
    return [
        decode(message, message.id in uncommitted, message.id in uncommitted and message.id == last)
        for message in snapshot.messages
    ]
