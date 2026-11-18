"""std/panels/input: Input, the program where you write to the log, and `llvim-input`, its command."""

import argparse
import asyncio
import sys
from collections.abc import Iterable

from llvim.core import Log
from llvim.std import env
from llvim.std.panels.input.bar import Bar, Hook, open_history, quit_session, send
from llvim.std.panels.input.commands import EXIT, HELP, QUIT, Command, Context, command
from llvim.std.panels.input.generate import CONTINUE
from llvim.std.panels.input.pane import Growth
from llvim.std.panels.keys import Panes

STANDARD = [QUIT, EXIT, HELP, CONTINUE]

__all__ = ["STANDARD", "Bar", "Command", "Context", "Hook", "Input", "command", "main", "quit_session", "send"]


class Input:
    """`Input(commands=[...], hooks=[...]).run()`. `log` defaults to the session's (`env.log`). The hooks run on each
    message sent (`bar.send`), not on commands or stops."""

    def __init__(self, commands: Iterable[Command] = STANDARD, log: Log | None = None, hooks: Iterable[Hook] = ()):
        self.commands, self.log, self.hooks = list(commands), log, list(hooks)

    async def send(self, log: Log, text: str) -> None:
        await send(log, text, self.hooks)

    def run(self) -> None:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            sys.exit("llvim-input needs a terminal")
        from llvim.std.panels.logviewer.screen import Screen

        history, save = open_history()
        log = self.log or env.log()
        try:
            with Screen(mouse=False, paste=True) as screen:
                bar = Bar(log, screen, Panes(), Growth(), history, commands=self.commands, send=self.send)
                try:
                    asyncio.run(bar.run())
                finally:
                    bar.growth.want(0)
                    save(bar.editor.history)
        except KeyboardInterrupt:
            pass


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="llvim-input", description="The input bar: write to a log.")
    ap.add_argument("log", nargs="?", default="main")
    ap.add_argument("-p", "--project", default=".", help="project folder (default: the working folder)")
    args = ap.parse_args(argv)
    Input(STANDARD, Log(args.project, args.log)).run()
