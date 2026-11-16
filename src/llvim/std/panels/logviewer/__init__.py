"""std/panels/logviewer: Viewer, the program that shows a log and follows it live, and `logviewer`, its command."""

import argparse
import asyncio
import sys
from collections.abc import Iterable

from llvim.core import Log
from llvim.std import env
from llvim.std.panels.logviewer.box import Box, Host, Renderer, alone, box
from llvim.std.panels.logviewer.plain import Printer, follow
from llvim.std.panels.logviewer.render import render, renderer

__all__ = ["Box", "Host", "Printer", "Renderer", "Viewer", "alone", "box", "main", "render", "renderer"]


class Viewer:
    """`Viewer(renderers=[...]).run()`. `log` defaults to the session's (`env.log`)."""

    def __init__(self, renderers: Iterable[Renderer] = (), log: Log | None = None, plain: bool = False, once: bool = False):
        self.renderers, self.log, self.plain, self.once = list(renderers), log, plain, once

    def run(self) -> None:
        log = self.log or env.log()
        try:
            if self.plain or self.once or not (sys.stdin.isatty() and sys.stdout.isatty()):
                asyncio.run(follow(log, self.once, self.renderers))
                return
            from llvim.std.panels.logviewer import app
            from llvim.std.panels.logviewer.screen import Screen

            with Screen() as screen:
                asyncio.run(app.Viewer(log, log.project, screen, renderers=self.renderers).run())
        except KeyboardInterrupt:
            pass


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="logviewer", description="Show a log and follow it live.")
    ap.add_argument("log", nargs="?", default="main")
    ap.add_argument("-p", "--project", default=".", help="project folder (default: the working folder)")
    ap.add_argument("--plain", action="store_true", help="print the log as plain text and follow it, even on a terminal")
    ap.add_argument("--once", action="store_true", help="print as plain text and exit instead of following")
    args = ap.parse_args(argv)
    Viewer((), Log(args.project, args.log), args.plain, args.once).run()
