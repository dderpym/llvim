"""session.py: Session, what a start script lays the panes of a session out with, and `llvim-run`, which runs what a
pane was given."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import os
import shlex
import subprocess
import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

from llvim.std.panels.keys import OPTION

SCRIPT_MODULE = "llvim_start"  # the name the start script is imported as, in every pane

type Run = str | Callable[[], Any]  # a shell command, or a function (or class) to call by name


def load(script: Path) -> ModuleType:
    """Import the start script (once per process), with its directory on the path so it can import files beside it."""
    script = script.resolve()
    if (module := sys.modules.get(SCRIPT_MODULE)) is not None and module.__file__ == str(script):
        return module
    sys.path.insert(0, str(script.parent))
    spec = importlib.util.spec_from_file_location(SCRIPT_MODULE, script)
    module = importlib.util.module_from_spec(spec)
    sys.modules[SCRIPT_MODULE] = module
    spec.loader.exec_module(module)
    return module


def _lookup(module: ModuleType, qualname: str) -> Any:
    obj: Any = module
    for part in qualname.split("."):
        obj = getattr(obj, part)
    return obj


def spec(fn: Callable[[], Any], script: Path) -> str:
    """What ``llvim-run`` is given to find ``fn`` again: ``<script>:<name>`` or ``<module>:<name>``. TypeError if it cannot be found
    by name (a lambda, a nested function), which is said now, in ``start``, rather than in a pane later."""
    module, name = getattr(fn, "__module__", None), getattr(fn, "__qualname__", "")
    try:
        found = _lookup(sys.modules[module], name) if module and "<" not in name else None
    except (KeyError, AttributeError):
        found = None
    if found is not fn:
        raise TypeError(f"{fn!r} cannot run in a pane: give a top-level function of the start script (or of a module), or a shell command")
    return f"{script.resolve() if module == SCRIPT_MODULE else module}:{name}"


def call(target: str) -> None:
    """Run ``<script.py>:<name>`` or ``<module>:<name>``: call it, then ``run()`` what it returns if that has one."""
    where, _, name = target.rpartition(":")
    module = load(Path(where)) if where.endswith(".py") else importlib.import_module(where)
    result = _lookup(module, name)()
    if callable(getattr(result, "run", None)):
        result.run()


class Pane:
    def __init__(self, session: Session, id: str):
        self.session, self.id = session, id

    def run(self, run: Run, name: str | None = None) -> None:
        """Run this in the pane, replacing what runs there. In ``here`` it starts once ``start`` has returned (it replaces it)."""
        if name:
            self.session.name(self, name)
        if self is self.session.here:
            self.session.here_runs = run
        else:
            self.session.tmux("respawn-pane", "-k", "-t", self.id, self.session.command(run))

    def focus(self) -> None:
        self.session.tmux("select-pane", "-t", self.id)

    def __repr__(self) -> str:
        return f"Pane({self.id})"


class Session:
    """What a start script lays panes out with: ``here`` (the first pane), ``split``, ``window``, and ``tmux`` for anything else.

    ``env`` is the environment, ``project`` the project directory and ``log`` the log's name (as ``llvim`` was started for)."""

    def __init__(self, script: Path, tmux: Callable[..., str] | None = None, here: str | None = None):
        self.script, self.env = script.resolve(), os.environ
        self.project = Path(self.env.get("LLVIM_PROJECT") or ".").resolve()
        self.log = self.env.get("LLVIM_LOG") or "main"
        self._tmux = tmux or _tmux
        self.here = Pane(self, here or self.env.get("TMUX_PANE") or "")
        self.here_runs: Run | None = None

    def tmux(self, *args: str) -> str:
        """Run a tmux command in this session's server and return what it printed."""
        return self._tmux(*args)

    def command(self, run: Run) -> str:
        """The shell command a pane runs for ``run``."""
        return run if isinstance(run, str) else "exec " + shlex.join(["llvim-run", spec(run, self.script)])

    def split(self, pane: Pane, *, below: int | str | None = None, above: int | str | None = None, right: int | str | None = None,
              left: int | str | None = None, run: Run, name: str | None = None) -> Pane:  # fmt: skip
        """A new pane beside ``pane``, on the side given, that many rows or columns (or ``"40%"``), running ``run``."""
        sides = {"below": below, "above": above, "right": right, "left": left}
        given = [(side, size) for side, size in sides.items() if size is not None]
        if len(given) != 1:
            raise TypeError("split needs one of below=, above=, right=, left= (rows or columns, or a percentage)")
        side, size = given[0]
        flags = {"below": ["-v"], "above": ["-v", "-b"], "right": ["-h"], "left": ["-h", "-b"]}[side]
        new = self.tmux("split-window", *flags, "-l", str(size), "-t", pane.id, "-c", str(self.project), "-P", "-F", "#{pane_id}", self.command(run))
        return self._made(new, name)

    def window(self, run: Run, name: str | None = None) -> Pane:
        """A new window in the background, running ``run`` (a provider, the runner: what has no need to be seen)."""
        new = self.tmux("new-window", "-d", "-c", str(self.project), "-P", "-F", "#{pane_id}", self.command(run))
        return self._made(new, name)

    def name(self, pane: Pane, name: str) -> None:
        """Let the panels of the pane's window find it as ``name`` (``viewer``, ``input``, ``status``: see ``llvim.std.panels.keys``)."""
        self.tmux("set-option", "-w", "-t", pane.id, OPTION + name, pane.id)

    def _made(self, out: str, name: str | None) -> Pane:
        pane = Pane(self, out.strip())
        if name:
            self.name(pane, name)
        return pane

    def finish(self) -> None:
        """After ``start``: become what ``here`` runs, or end (the first pane closes)."""
        if self.here_runs is not None:
            os.execvp("sh", ["sh", "-c", self.command(self.here_runs)])


def _tmux(*args: str) -> str:
    r = subprocess.run(["tmux", *args], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"tmux {args[0]}: {r.stderr.strip()}")
    return r.stdout


def start(script: Path) -> None:
    """Run a start script: import it, call its ``start(session)``, then become what it said runs here."""
    module = load(script)
    if not callable(getattr(module, "start", None)):
        sys.exit(f"llvim: {script} has no start(session) function")
    session = Session(script)
    module.start(session)
    session.finish()


def main(argv: list[str] | None = None) -> None:
    """``llvim-run <script.py>:<name>`` or ``<module>:<name>`` runs one pane's program; ``llvim-run --start <script.py>`` a session.
    A pane whose program fails shows why, and waits for Enter before it closes."""
    ap = argparse.ArgumentParser(prog="llvim-run", description="Run what a start script put in a pane.")
    ap.add_argument("target", help="<script.py>:<name>, <module>:<name>, or with --start the start script")
    ap.add_argument("--start", action="store_true", help="run the start script's start(session)")
    args = ap.parse_args(argv)
    try:
        start(Path(args.target)) if args.start else call(args.target)
    except KeyboardInterrupt:
        pass
    except SystemExit as e:
        if e.code not in (None, 0):
            print(e.code if isinstance(e.code, str) else f"exit {e.code}", file=sys.stderr)
            _hold()
        raise
    except Exception:
        traceback.print_exc()
        _hold()
        sys.exit(1)


def _hold() -> None:
    if sys.stdin.isatty():
        try:
            input("\n[llvim-run: press Enter to close]")
        except (EOFError, KeyboardInterrupt):
            pass
