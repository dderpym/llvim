"""std/panels/input/bar.py: Bar, the input bar: the editor, the menu and the notice, what each key does to them, and
sending what was typed to the log."""

from __future__ import annotations

import asyncio
import getpass
import inspect
import os
import subprocess
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from contextlib import aclosing
from typing import Any

from llvim.core import Author, Log, Request
from llvim.std import env
from llvim.std.conversation import Info, Tag, encode
from llvim.std.cues import GENERATE, busy, cue, cued
from llvim.std.panels.input import view
from llvim.std.panels.input.commands import Command, Context
from llvim.std.panels.input.complete import Suggestion, command_name, complete
from llvim.std.panels.input.editor import Editor, handle, load_history, save_history
from llvim.std.panels.input.menu import Menu
from llvim.std.panels.input.pane import Growth
from llvim.std.panels.keys import PAGE_DOWN, PAGE_UP, WHEEL_DOWN, WHEEL_UP, Key, Mouse, Outcome, Panes, Redirect, route

PRIORITY = 0  # a provider's default: a message waits for the model's turn to end, it does not cut it short
STOP_PRIORITY = 100  # above any provider: stopping is what cuts a turn short
STOPPED = "User stopped this response."
ENTER, TAB, SHIFT_TAB, ESC, CTRL_C, CTRL_D, CTRL_L = (b"\r", b"\n"), b"\t", b"\x1b[Z", b"\x1b", b"\x03", b"\x04", b"\x0c"
PASTE_START, PASTE_END = b"\x1b[200~", b"\x1b[201~"
VIEWER_KEYS = (*PAGE_UP, *PAGE_DOWN)  # scrolling is the viewer's: the bar passes these on without taking the focus


async def idle(log: Log) -> None:
    """Return once the turn is over (`cues.busy`)."""
    async with aclosing(log.changes()) as changes:
        async for _ in changes:
            if not busy(log):
                return


async def send(log: Log, text: str) -> None:
    """Commit `text` as a user message with a cue for the model, once the turn in progress is over."""
    user = getpass.getuser()
    while True:
        await idle(log)
        async with await log.claim(Request(PRIORITY, {Info.INPUT: user})) as writer:
            if cued(log.read()) is not None:
                continue  # someone cued the model while we waited for the log: its turn comes first
            writer.append(encode([Tag.USER], text))
            writer.append(cue(GENERATE))
            await writer.commit(author=Author(user))
            return


async def stop(log: Log) -> None:
    """Take the log from the model at once and say so, with no cue: nothing answers it."""
    user = getpass.getuser()
    async with await log.claim(Request(STOP_PRIORITY, {Info.INPUT: user})) as writer:
        writer.append(encode([Tag.USER, Tag.STOP], STOPPED))
        await writer.commit(author=Author(user), message="stop")


def quit_session() -> None:
    """End the tmux session this bar runs in, and everything in it. Outside tmux there is none to end."""
    pane = os.environ.get("TMUX_PANE")
    if not (os.environ.get("TMUX") and pane):
        return
    shown = subprocess.run(["tmux", "display-message", "-p", "-t", pane, "#{session_id}"], capture_output=True, text=True)
    if session := shown.stdout.strip():
        subprocess.run(["tmux", "kill-session", "-t", session])


class Bar:
    def __init__(
        self,
        log: Log,
        screen: Any,
        panes: Panes,
        growth: Growth,
        history: list[str] | None = None,
        commands: Iterable[Command] = (),
        send: Callable[[Log, str], Awaitable[None]] = send,
        quit: Callable[[], None] = quit_session,
        stop: Callable[[Log], Awaitable[None]] = stop,
        busy: Callable[[Log], bool] = busy,
    ):
        self.log, self.screen, self.panes, self.growth = log, screen, panes, growth
        self.commands = {c.name: c for c in commands}
        self.editor, self.menu, self.notice = Editor(history), Menu(), ""
        self._send, self._quit, self._stop, self._busy = send, quit, stop, busy
        self.outbox: deque[str] = deque()
        self._sending: asyncio.Task | None = None
        self._stopping: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()
        self._poke = asyncio.Event()
        self.pasting, self.done = False, False

    # --- keys ---

    def on_key(self, raw: bytes) -> None:
        self.notice = ""
        if raw == PASTE_START or raw == PASTE_END:
            self.pasting = raw == PASTE_START
        elif self.pasting:
            self.editor.insert("\n" if raw in ENTER else (raw.decode(errors="ignore") if raw != ESC else ""))
        else:
            decision = route(raw, self.own_keys, self.to_viewer)
            if isinstance(decision, Redirect):
                self.panes.apply(decision)
        self.refresh()

    def own_keys(self, raw: bytes) -> Outcome:
        e, m = self.editor, self.menu
        if raw in ENTER:
            if m.shown and m.current():
                self.accept(m.current())
            else:
                self.submit()
        elif raw == TAB:
            self.tab()
        elif raw == SHIFT_TAB and m.shown:
            m.move(-1)
        elif raw == ESC:
            m.dismiss(e.text) if m.shown else None
        elif raw == CTRL_C:
            self.interrupt()
        elif raw == CTRL_D:
            pass  # does not close the bar
        elif raw == CTRL_L:
            self.screen.invalidate()
        elif m.shown and raw in (b"\x1b[A", b"\x1bOA", b"\x10"):
            m.move(-1)
        elif m.shown and raw in (b"\x1b[B", b"\x1bOB", b"\x0e"):
            m.move(1)
        elif handle(e, raw):
            m.open() if e.text != m.dismissed else None
        else:
            return Outcome.PASS
        return Outcome.HANDLED

    def to_viewer(self, raw: bytes) -> Redirect | Outcome:
        return Redirect("viewer", raw, focus=False) if raw in VIEWER_KEYS else Outcome.PASS

    def on_mouse(self, ev: Mouse) -> None:
        if ev.button in (WHEEL_UP, WHEEL_DOWN):
            self.panes.apply(Redirect("viewer", PAGE_UP[0] if ev.button == WHEEL_UP else PAGE_DOWN[0], focus=False))

    def tab(self) -> None:
        """Choose the first suggestion, or take the one chosen (the only suggestion is taken at once)."""
        m = self.menu
        if not m.items:
            return
        m.open()
        if m.current() is None and len(m.items) > 1:
            m.move(1)
        else:
            self.accept(m.current() or m.items[0])

    def accept(self, s: Suggestion) -> None:
        e = self.editor
        e.text = e.text[: s.start] + s.text + s.then + e.text[s.end :]
        e.cursor = s.start + len(s.text) + len(s.then)
        self.menu.selected = None

    def refresh(self) -> None:
        e = self.editor
        self.menu.refresh(complete(e.text, e.cursor, self.commands), e.text)

    # --- sending ---

    def submit(self) -> None:
        text = self.editor.text.strip()
        if not text:
            return
        if name := command_name(text):
            self.editor.submit()
            if cmd := self.commands.get(name):
                self._run_command(cmd, text.partition(" ")[2].strip())
            else:
                self.say(f"unknown command /{name} (see /help); start with // to send a slash")
            return
        if text.startswith("//"):
            text = text[1:]
        if self.outbox or self._busy(self.log):
            self.say("queued: it goes in when the model's turn is over (ctrl-c stops the model)")
        self.outbox.append(text)
        self.editor.submit()
        if self._sending is None or self._sending.done():
            self._sending = self._start(self._deliver())

    async def _deliver(self) -> None:
        """Send the outbox one message at a time, in the order they were typed."""
        while self.outbox:
            try:
                await self._send(self.log, self.outbox[0])
            except Exception as error:
                self.say(f"not sent: {error}")
            self.outbox.popleft()
            self._poke.set()

    def _run_command(self, cmd: Command, arg: str) -> None:
        context = Context(self.log, self.say, self.quit, self.commands, self.panes)
        try:
            result = cmd.run(context, arg)
        except Exception as error:
            self.say(f"/{cmd.name} failed: {error}")
            return
        if inspect.isawaitable(result):
            self._start(self._finish(cmd, result))

    async def _finish(self, cmd: Command, result: Awaitable[None]) -> None:
        try:
            await result
        except Exception as error:
            self.say(f"/{cmd.name} failed: {error}")

    def interrupt(self) -> None:
        """Ctrl-C: stop the model if it is working (the line is kept), else clear the line."""
        if not self._busy(self.log):
            self.editor.clear()
        elif self._stopping is None or self._stopping.done():
            self._stopping = self._start(self._stop(self.log))
            self.say("stopping...")

    def _start(self, work: Awaitable[None]) -> asyncio.Task:
        """Run `work` beside the keyboard, and draw again when it ends."""
        task = asyncio.ensure_future(work)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(lambda _: self._poke.set())
        return task

    def say(self, text: str) -> None:
        self.notice = text
        self._poke.set()

    def quit(self) -> None:
        self.done = True
        self._quit()

    # --- the screen ---

    def draw(self) -> None:
        self.refresh()
        cols, _ = self.screen.size()
        self.growth.want(view.wanted(self.menu) + view.prompt_height(self.editor, cols) - view.INPUT_ROWS)
        cols, rows = self.screen.size()  # after: the pane is its new height by now, so what is drawn is drawn for that
        queued = f"{len(self.outbox)} queued" if self.outbox else ""
        self.screen.draw(*view.render(self.editor, self.menu, self.notice or queued, cols, rows))

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        fds = self.screen.fds()
        for fd in fds:
            loop.add_reader(fd, self._poke.set)
        try:
            self.draw()
            while not self.done:
                await self._poke.wait()
                self._poke.clear()
                if not self._take_input():
                    return
                self.draw()
        finally:
            for fd in fds:
                loop.remove_reader(fd)
            for task in list(self._tasks):
                task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def _take_input(self) -> bool:
        """Handle what the terminal sent. False once the bar is done."""
        try:
            events = self.screen.read()
        except EOFError:
            return False
        for ev in events:
            if isinstance(ev, Key):
                self.on_key(ev.raw)
            elif isinstance(ev, Mouse):
                self.on_mouse(ev)
            if self.done:
                return False
        return True


def open_history() -> tuple[list[str], Callable[[list[str]], None]]:
    path = env.home() / "input_history"
    return load_history(path), lambda history: save_history(path, history)
