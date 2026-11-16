"""std/panels/input/commands.py: Command and Context, the slash commands of the input bar, and the basic ones."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class Context:
    """What a command may use: the log, a line to say something under the prompt, and a way to end the session."""

    log: Any
    notice: Callable[[str], None]
    quit: Callable[[], None]
    commands: dict[str, Command]
    panes: Any = None  # ``llvim.std.panels.keys.Panes``: to move the focus to another panel
    queue: Callable[[str, Callable[[Any], Awaitable[None]]], None] | None = None  # the bar's queue: work done in turn


@dataclass(frozen=True)
class Command:
    name: str
    help: str
    run: Callable[[Context, str], Awaitable[None] | None]  # the bar awaits what it returns, beside the keyboard
    complete: Callable[[str], list[tuple[str, str]]] | None = None  # (argument, help) for the text typed after the command


def command(name: str, help: str, complete: Callable[[str], list[tuple[str, str]]] | None = None):
    """Decorator: the function as the ``Command`` ``/name``."""
    return lambda fn: Command(name, help, fn, complete)


def _quit(ctx: Context, arg: str) -> None:
    ctx.quit()


def _help(ctx: Context, arg: str) -> None:
    ctx.notice("commands: " + "  ".join(f"/{n}" for n in sorted(ctx.commands)) + "   (start a line with // to send a slash)")


QUIT = Command("quit", "end the session", _quit)
EXIT = Command("exit", "end the session", _quit)
HELP = Command("help", "list the commands", _help)
