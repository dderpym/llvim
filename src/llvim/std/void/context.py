"""std/void/context.py: CONTEXT, the context renderer that leaves voided messages out of what a model is sent."""

from llvim.std.conversation import Entry
from llvim.std.void.tag import is_void


def without_void(entries: list[Entry]) -> list[Entry]:
    return [entry for entry in entries if not is_void(entry)]


CONTEXT = without_void
