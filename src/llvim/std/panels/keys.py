"""std/panels/keys.py: what a panel does with a key (Outcome, Redirect, route), finding the other panels (Panes), and
splitting terminal input into keys and mouse events (parse)."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

OPTION = "@llvim_pane_"


class Outcome(StrEnum):
    HANDLED = "handled"
    PASS = "pass"


@dataclass(frozen=True)
class Redirect:
    """Give these keys to another panel, and (by default) move focus there so the keys after them go there too."""

    panel: str
    keys: bytes = b""  # nothing to send: only move focus
    focus: bool = True


Decision = Outcome | Redirect
Handler = Callable[[bytes], Decision]


def route(raw: bytes, *handlers: Handler) -> Decision:
    """The first decision that is not PASS, asking the handlers in order. PASS if none has one."""
    for handler in handlers:
        decision = handler(raw)
        if decision is not Outcome.PASS:
            return decision
    return Outcome.PASS


def tmux(args: list[str]) -> str:
    """Run a tmux command from outside its server's connection: the way a panel with no connection of its own does."""
    return subprocess.run(["tmux", *args], capture_output=True, text=True).stdout


def over(control) -> Callable[[list[str]], str]:
    """Run tmux commands over a control-mode connection (``llvim.std.tmux.Control``), which is much quicker than a process each.

    ``control`` may be the connection or a function that gives it, so it can be made when first needed.
    """
    return lambda args: (control() if callable(control) else control).run(shlex.join(args))


class Panes:
    """The panes of this session by name, and moving keys and focus between them."""

    def __init__(self, run: Callable[[list[str]], str] | None = None, here: str | None = None):
        self._run = run or tmux
        self.here = os.environ.get("TMUX_PANE") if here is None else here  # this panel's own pane
        self._ids: dict[str, str | None] = {}

    def id(self, name: str) -> str | None:
        """The pane id of the panel with this name, or None if there is none (or this is not in a tmux layout)."""
        if not self.here:
            return None
        if name not in self._ids:
            try:
                found = self._run(["show-options", "-wqv", "-t", self.here, OPTION + name]).strip()
            except Exception:
                found = ""
            self._ids[name] = found or None
        return self._ids[name]

    def known(self, name: str) -> bool:
        """Is there a panel to redirect to? False for this panel itself."""
        return (pane := self.id(name)) is not None and pane != self.here

    def apply(self, decision: Redirect) -> bool:
        """Carry out a redirect. False if the panel is not known or tmux refused: the keys went nowhere."""
        if not self.known(decision.panel):
            return False
        pane = self.id(decision.panel)
        try:
            if decision.keys:
                self._run(["send-keys", "-t", pane, "-H", *(f"{b:02x}" for b in decision.keys)])
            if decision.focus:
                self._run(["select-pane", "-t", pane])
        except Exception:
            self._ids.pop(decision.panel, None)  # the pane may be gone: look it up again next time
            return False
        return True


# --- what a terminal sends ---

WHEEL_UP, WHEEL_DOWN = 64, 65

UP, DOWN, PAGE_UP, PAGE_DOWN, HOME, END = (
    (b"\x1b[A", b"\x1bOA"), (b"\x1b[B", b"\x1bOB"), (b"\x1b[5~",), (b"\x1b[6~",), (b"\x1b[H", b"\x1b[1~", b"\x1bOH"), (b"\x1b[F", b"\x1b[4~", b"\x1bOF"),
)  # fmt: skip


@dataclass(frozen=True)
class Key:
    raw: bytes  # exactly the bytes the terminal sent, so they can be passed on to a program unchanged


@dataclass(frozen=True)
class Mouse:
    button: int
    x: int  # 0-based
    y: int
    press: bool


_MOUSE = re.compile(rb"\x1b\[<(\d+);(\d+);(\d+)([Mm])")
_KEY = re.compile(rb"\x1b\[[0-9;:<=>?]*[ -/]*[@-~]|\x1bO.|\x1b.|[\xc0-\xff][\x80-\xbf]*|.", re.S)


def parse(data: bytes) -> list[Key | Mouse]:
    """Split what the terminal sent into mouse events and keys (an escape sequence is one key)."""
    out: list[Key | Mouse] = []
    i = 0
    while i < len(data):
        m = _MOUSE.match(data, i)
        if m:
            out.append(Mouse(int(m[1]), int(m[2]) - 1, int(m[3]) - 1, m[4] == b"M"))
        else:
            m = _KEY.match(data, i)
            out.append(Key(m[0]))
        i = m.end()
    return out
