"""std/panels/logviewer/box.py: Box, what a renderer makes to show its messages, Host, what a box talks to, and Renderer."""

from __future__ import annotations

import threading
from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass
from typing import Any

from llvim.std.conversation import Entry

@dataclass
class Hooks:
    """What a box registered with the host."""

    on_messages: Callable[[list[Entry]], None] | None = None
    layout: Callable[[int], list[str]] | None = None
    focusable: Callable[[], bool] | bool = False
    on_focus: Callable[[bool], None] | None = None
    on_key: Callable[[bytes], None] | None = None
    cursor: Callable[[], tuple[int, int] | None] | None = None
    text: Callable[[], str] | None = None
    on_close: Callable[[], None] | None = None
    on_click: Callable[[], None] | None = None


class Box:
    framed = True  # a box that draws itself with a frame (╭│╰) has it left out of copied text; one that draws plain text sets False

    def __init__(self, host: Host, messages: list[Entry]):
        self.host, self.messages = host, messages
        self.lines: list[str] = []
        self.hooks = Hooks()
        self.closed = threading.Event()  # set when the box is dropped; an update loop waits on it instead of sleeping
        self._dirty = True  # its rows must be worked out again (see ``changed``)
        self.error: Exception | None = None  # set if its update raised: the viewer then shows the fallback instead
        self._laid: tuple[int, list[str], list[bool]] | None = None  # the viewer's last layout: (width, rows, joined)
        self._epoch = -1  # the viewer's count of "something changed that no box said" when this was laid out

    def update(self) -> None:
        """Work that runs beside the viewer. Nothing, unless ``__init__`` started it."""

    def changed(self) -> None:
        """What this box shows is different now: draw again. Safe to call from any thread.

        Say it with this, not ``host.changed()``, when you have a ``layout`` hook: the viewer then works out the rows of this box
        alone, instead of every box that draws itself.
        """
        self._dirty = True
        self.host.changed(self)

    def text(self) -> str:
        """Plain text for this box: what its ``text`` hook says, else its lines."""
        return self.hooks.text() if self.hooks.text else "\n".join(self.lines)

    def close(self) -> None:
        self.closed.set()
        if self.hooks.on_close:
            try:
                self.hooks.on_close()
            except Exception:
                pass


class Host:
    """What the viewer gives a box. ``live`` is False when printing plain text: nothing is started."""

    live = True
    cols = 80  # the width of the screen
    project = None  # the project directory

    def changed(self, box: Box | None = None) -> None:
        """Something a box shows is different now: draw again. Safe to call from any thread. ``box`` says which, if known."""

    def control(self) -> Any:
        """The tmux connection (``llvim.std.tmux.Control``), made when first asked for."""
        raise RuntimeError("no tmux connection")

    def request_focus(self, box: Box) -> None:
        """Give this box the keyboard, if it is focusable and on screen to be had (a box asks once, when it wants it)."""

    def start(self, fn: Callable[[], None]) -> None:
        """Run ``fn`` (a box's ``update``) in its own thread. If it raises, the box is marked failed."""
        if not self.live:
            return
        box = getattr(fn, "__self__", None)

        def run() -> None:
            try:
                fn()
            except Exception as e:
                if box is not None:
                    box.error = e
                self.changed()

        threading.Thread(target=run, daemon=True).start()

    # --- the hooks: each one is set on the box that registers it ---

    def on_messages(self, box: Box, fn: Callable[[list[Entry]], None]) -> None:
        box.hooks.on_messages = fn

    def layout(self, box: Box, fn: Callable[[int], list[str]]) -> None:
        box.hooks.layout = fn

    def focusable(self, box: Box, fn: Callable[[], bool] | bool) -> None:
        box.hooks.focusable = fn

    def on_focus(self, box: Box, fn: Callable[[bool], None]) -> None:
        box.hooks.on_focus = fn

    def on_key(self, box: Box, fn: Callable[[bytes], None]) -> None:
        box.hooks.on_key = fn

    def cursor(self, box: Box, fn: Callable[[], tuple[int, int] | None]) -> None:
        box.hooks.cursor = fn

    def text(self, box: Box, fn: Callable[[], str]) -> None:
        box.hooks.text = fn

    def on_close(self, box: Box, fn: Callable[[], None]) -> None:
        box.hooks.on_close = fn

    def on_click(self, box: Box, fn: Callable[[], None]) -> None:
        box.hooks.on_click = fn


# --- renderers ---


@dataclass(frozen=True)
class Renderer:
    claim: Callable[[Entry], Hashable | None]  # a group key if these messages are mine, else None
    make: Callable[[Host, list[Entry]], Box]
    name: str = ""


def alone(m: Entry) -> int:
    """A claim that takes just this message."""
    return m.id


def box(claim: Callable[[Entry], Hashable | None]):
    """Decorator: a Box class (or any ``(host, messages) -> Box``) as the ``Renderer`` for the messages ``claim`` takes.

    Messages that get the same key from one claim go to one box, in the order of the first of them; None means not yours.
    The renderer is a value: give it to a viewer (``Viewer(renderers=[...])``)."""
    return lambda cls: Renderer(claim, cls, getattr(cls, "__name__", ""))


def chain(renderers: Iterable[Renderer] = ()) -> list[Renderer]:
    """The renderers a viewer asks, in order: those it was given, then the built-in ones (the last claims everything)."""
    from llvim.std.panels.logviewer import boxes

    return [*renderers, *boxes.BUILTIN]


def claimed(renderers: list[Renderer], m: Entry) -> tuple[int | None, Hashable | None]:
    """Which renderer takes this message, and under what key: the first claim that is not None."""
    for i, r in enumerate(renderers):
        try:
            key = r.claim(m)
        except Exception:
            continue  # a claim that fails does not claim
        if key is not None:
            return i, key
    return None, None


def group(messages: list[Entry], renderers: list[Renderer]) -> dict[tuple[int, Hashable], tuple[Renderer, list[Entry]]]:
    """Split messages into the groups each renderer claims, keeping the order of first appearance."""
    groups: dict = {}
    for m in messages:
        i, key = claimed(renderers, m)
        if i is not None:
            groups.setdefault((i, key), (renderers[i], []))[1].append(m)
    return groups


def make(renderer: Renderer, host: Host, messages: list[Entry]) -> Box:
    """The renderer's box for these messages, or the fallback's if it raises."""
    from llvim.std.panels.logviewer import boxes

    try:
        return renderer.make(host, messages)
    except Exception:
        return boxes.Fallback(host, messages)
