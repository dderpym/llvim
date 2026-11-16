"""std/panels/logviewer/render.py: renderer, a text function as a renderer, and render, one message as plain text."""

from collections.abc import Callable

from llvim.std.conversation import Entry
from llvim.std.panels.logviewer.box import Host, Renderer, alone, chain
from llvim.std.panels.logviewer.boxes import Static


class PlainHost(Host):
    live = False


def renderer(match: Callable):
    """Decorator: `fn(tags, content) -> str` as the Renderer of the messages whose tags `match` accepts."""
    return lambda fn: Renderer(
        lambda m: alone(m) if match(m.tags) else None,
        lambda host, messages: Static(host, messages, fn),
        getattr(fn, "__name__", ""),
    )


def render(m: Entry, renderers: list[Renderer] | None = None) -> str:
    """The text of the first renderer that claims `m` and makes a box that gives text. One that fails is skipped."""
    host = PlainHost()
    for r in chain() if renderers is None else renderers:
        try:
            if r.claim(m) is None:
                continue
            out = r.make(host, [m]).text()
        except Exception:
            continue
        if isinstance(out, str):
            return out
    raise AssertionError("the fallback claims everything and always renders")
