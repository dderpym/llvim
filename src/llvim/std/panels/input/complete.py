"""std/panels/input/complete.py: Suggestion, and what to suggest for the line being typed."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from llvim.std.panels.input.commands import Command

WORD = re.compile(r"/(\w*)")  # the first word of a line that starts with a slash
ARGS = re.compile(r"/(\w+)\s+(.*)", re.S)


@dataclass(frozen=True)
class Suggestion:
    """Replace ``line[start:end]`` with ``text`` (and ``then`` after it, to carry on typing)."""

    text: str
    start: int
    end: int
    help: str = ""
    then: str = ""


def command_name(line: str) -> str | None:
    """The command a line names (``"/quit now"`` -> ``"quit"``), or None if it is a message (``"/etc/hosts"``, ``"//quit"``, ``"/ hi"``)."""
    m = re.fullmatch(r"/([A-Za-z]+)(?:\s.*)?", line, re.S)
    return m[1].lower() if m else None


def complete(line: str, cursor: int, commands: Mapping[str, Command]) -> list[Suggestion]:
    """The suggestions for this line with the cursor here: command names while typing the first word, then a command's arguments."""
    if not line.startswith("/") or line.startswith("//"):
        return []
    first = WORD.match(line)
    if first and cursor <= first.end() and (first.end() == len(line) or line[first.end()].isspace()):
        typed = first[1].lower()
        return [
            Suggestion(f"/{c.name}", 0, first.end(), c.help, " " if c.complete else "")
            for c in sorted(commands.values(), key=lambda c: c.name)
            if c.name.startswith(typed)
        ]
    m = ARGS.fullmatch(line)
    if m and (c := commands.get(m[1].lower())) and c.complete and cursor >= m.start(2):
        return [Suggestion(arg, m.start(2), len(line), help) for arg, help in c.complete(m[2]) if arg != m[2]]
    return []
