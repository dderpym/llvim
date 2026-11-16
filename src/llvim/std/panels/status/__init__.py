"""std/panels/status: Status, the one-line panel that shows what is happening to the log, and `llvim-status`, its
command."""

import argparse
import asyncio
import sys
from collections.abc import Iterable

from llvim.core import Log
from llvim.std import env
from llvim.std.panels.status.bar import State, StatusBar, StatusRenderer, compose
from llvim.std.panels.status.renderers import BUILTIN, activity, model

__all__ = ["BUILTIN", "State", "Status", "StatusBar", "StatusRenderer", "activity", "compose", "main", "model"]


class Status:
    """`Status(renderers=[...]).run()`: the renderers, in order (default `BUILTIN`). `log` defaults to the session's."""

    def __init__(self, renderers: Iterable[StatusRenderer] = BUILTIN, log: Log | None = None):
        self.renderers, self.log = list(renderers), log

    def run(self) -> None:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            sys.exit("llvim-status needs a terminal")
        from llvim.std.panels.logviewer.screen import Screen

        log = self.log or env.log()
        try:
            with Screen(mouse=False) as screen:
                asyncio.run(StatusBar(log, screen, self.renderers).run())
        except KeyboardInterrupt:
            pass


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="llvim-status", description="A line that shows what is happening to a log.")
    ap.add_argument("log", nargs="?", default="main")
    ap.add_argument("-p", "--project", default=".", help="project folder (default: the working folder)")
    args = ap.parse_args(argv)
    Status(BUILTIN, Log(args.project, args.log)).run()
