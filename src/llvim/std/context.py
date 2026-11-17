"""std/context.py: ContextRenderer, a step between a log and a program that reads it as a conversation."""

from collections.abc import Callable, Iterable

from llvim.std.conversation import Entry

type ContextRenderer = Callable[[list[Entry]], list[Entry]]


def render(entries: list[Entry], renderers: Iterable[ContextRenderer]) -> list[Entry]:
    """The entries as each renderer in turn leaves them."""
    for renderer in renderers:
        entries = renderer(entries)
    return entries
