"""std/void/tag.py: the void tag: a message that is still in the log and no longer in the conversation."""

import dataclasses
import json

from llvim.std.conversation import Entry

VOID = "void"


def is_void(entry: Entry) -> bool:
    return VOID in entry.tags


def unmarked(entry: Entry) -> Entry:
    """The entry as it was before it was voided, for asking what kind of message it is."""
    return dataclasses.replace(entry, tags=[tag for tag in entry.tags if tag != VOID]) if is_void(entry) else entry


def marked(content: bytes, void: bool) -> bytes | None:
    """The message with the void tag put on (or taken off), its text untouched. None if that changes nothing, or the message is
    in no format that has tags."""
    header, newline, body = content.partition(b"\n")
    try:
        meta = json.loads(header) if newline else None
    except ValueError:
        return None
    if not isinstance(meta, dict) or not isinstance(meta.get("tags"), list) or (VOID in meta["tags"]) == void:
        return None
    meta["tags"] = [*meta["tags"], VOID] if void else [tag for tag in meta["tags"] if tag != VOID]
    return json.dumps(meta, ensure_ascii=False).encode() + b"\n" + body
