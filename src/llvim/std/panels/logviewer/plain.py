"""std/panels/logviewer/plain.py: Printer, the log as plain text that only grows, and follow, which prints it live."""

import sys
from collections.abc import Iterable
from contextlib import aclosing

from llvim.core import Log, Message, Snapshot
from llvim.std.conversation import decode
from llvim.std.panels.logviewer.box import Renderer, chain
from llvim.std.panels.logviewer.render import render
from llvim.std.panels.logviewer.text import CLEAR, partial


class Printer:
    def __init__(self, renderers: Iterable[Renderer] = ()):
        self.chain = chain(renderers)
        self._printed: list[str] = []
        self._texts: dict[int, tuple[Message, bool, bool, str]] = {}

    def update(self, snapshot: Snapshot) -> str:
        """What to write to bring the terminal up to date: the new text, or CLEAR and everything if what was printed changed."""
        texts = self._all(snapshot)
        printed, self._printed = self._printed, texts
        if texts == printed:
            return ""
        last = len(printed) - 1
        if printed and len(texts) > last and texts[:last] == printed[:last] and texts[last].startswith(printed[last]):
            return texts[last][len(printed[last]) :] + "".join(texts[last + 1 :])
        return (CLEAR if printed else "") + "".join(texts)

    def _all(self, snapshot: Snapshot) -> list[str]:
        uncommitted = {m.id for m in snapshot.uncommitted}
        last = snapshot.messages[-1].id if snapshot.messages else None
        texts, kept = [], {}
        for message in snapshot.messages:
            fresh = message.id in uncommitted
            streaming = fresh and message.id == last
            cached = self._texts.get(message.id)
            if cached is None or cached[:3] != (message, fresh, streaming):
                entry = decode(message, fresh, streaming)
                text = partial(entry.tags, entry.content) if streaming else render(entry, self.chain)
                cached = (message, fresh, streaming, text)
            kept[message.id] = cached
            texts.append(cached[3])
        self._texts = kept
        return texts


async def follow(log: Log, once: bool = False, renderers: Iterable[Renderer] = ()) -> None:
    """Print the log, then what changes, until cancelled. Scrolling is the terminal's."""
    printer = Printer(renderers)
    if once:
        _write(printer.update(log.read()))
        return
    async with aclosing(log.changes()) as changes:
        async for snapshot in changes:
            _write(printer.update(snapshot))


def _write(text: str) -> None:
    if text:
        sys.stdout.write(text)
        sys.stdout.flush()
