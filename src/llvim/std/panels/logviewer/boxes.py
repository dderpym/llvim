"""std/panels/logviewer/boxes.py: the built-in boxes: thinking, which folds; markdown, for what the model says; cues,
which show nothing; and the fallback, which shows anything."""

from __future__ import annotations

from collections.abc import Callable

from llvim.std.conversation import Entry, Tag
from llvim.std.panels.logviewer import markdown, text
from llvim.std.panels.logviewer.box import Box, Host, Renderer, alone


def lines_of(s: str) -> list[str]:
    return s.split("\n")


class Fallback(Box):
    """The tags in bold, then the content. Any messages at all."""

    def __init__(self, host: Host, messages: list[Entry]):
        super().__init__(host, messages)
        self.lines = lines_of("".join(self.render(m) for m in messages))

    def render(self, m: Entry) -> str:
        return text.partial(m.tags, m.content) if m.streaming else text.default(m.tags, m.content)


class Thinking(Box):
    """A thinking message, its markdown drawn all in grey. While it streams it shows in full. When it is finished it folds to one
    line, and a click opens it again (and folds it again)."""

    framed = False

    def __init__(self, host: Host, messages: list[Entry]):
        super().__init__(host, messages)
        self.m = messages[0]
        self.streaming = self.m.streaming
        self.body = text.clean(self.m.content)
        self.expanded = False
        host.layout(self, self.rows)
        host.on_click(self, self.toggle)
        host.text(self, lambda: text.thinking(self.m.tags, self.m.content))  # plain output and copying get all of it, as written

    def toggle(self) -> None:
        if not self.streaming:
            self.expanded = not self.expanded
            self.changed()

    def rows(self, cols: int) -> list[str]:
        head = lambda label: f"{text.GREY_HEAD}{label}{text.RESET}"  # noqa: E731
        if not self.streaming and not self.expanded:
            return [f"{head('▸ [thinking]')} {text.GREY}{len(self.body.split())} words · click to open{text.RESET}"]
        body = markdown.render(self.body, cols, tone=text.GREY)
        return [head("thinking" if self.streaming else "▾ [thinking]"), *body]


class Markdown(Box):
    """An assistant message, with its markdown drawn (see ``markdown``). It lays itself out for the width of the screen."""

    framed = False  # its rows are text, so copying them keeps every character

    def __init__(self, host: Host, messages: list[Entry]):
        super().__init__(host, messages)
        self.m = messages[0]
        host.layout(self, self.rows)
        host.text(self, lambda: text.default(self.m.tags, self.m.content))  # plain output stays what was written

    def rows(self, cols: int) -> list[str]:
        body = markdown.render(text.clean(self.m.content), cols)
        head = f"{text.HEAD}{text.tags_text(self.m.tags)}{text.RESET}"
        return [head, *body] if self.m.streaming else [head, *body, "", ""]


def is_assistant(m: Entry) -> bool:
    return m.tags[:1] == [Tag.ASSISTANT]


class Hidden(Box):
    """A message that is only for the programs."""

    framed = False


def is_cue(m: Entry) -> bool:
    return m.tags[:1] == [Tag.CUE]


class Static(Box):
    """A text renderer of the old kind, ``fn(tags, content) -> str``, as a box."""

    def __init__(self, host: Host, messages: list[Entry], fn: Callable):
        super().__init__(host, messages)
        self.lines = lines_of("".join(fn(m.tags, text.clean(m.content)) for m in messages))


BUILTIN = [
    Renderer(lambda m: alone(m) if text.is_thinking(m.tags) else None, Thinking, "thinking"),
    Renderer(lambda m: alone(m) if is_assistant(m) else None, Markdown, "markdown"),
    Renderer(lambda m: alone(m) if is_cue(m) else None, Hidden, "hidden"),
    Renderer(alone, Fallback, "fallback"),
]
