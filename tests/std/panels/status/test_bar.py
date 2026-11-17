"""std/panels/status/bar.py: the bar updates each status renderer with the state of the log and puts their pieces in one line."""

import asyncio

from llvim.core import Request
from llvim.std.panels.logviewer.ansi import strip, width
from llvim.std.panels.status.bar import StatusBar, compose


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def test_the_pieces_that_are_not_empty_are_joined_in_order_and_fill_the_width():
    line = compose(["one", None, "", "two"], 20)
    assert strip(line).rstrip() == " one · two" and width(line) == 20


def test_a_line_too_long_for_the_width_is_cut_and_marked():
    line = compose(["x" * 50], 20)
    assert width(line) == 20 and strip(line).endswith("…")


def test_each_renderer_gets_the_last_message_the_holder_and_the_model_and_one_that_raises_shows_nothing(
    fake_log, stub_screen
):
    seen = []
    fake_log.say(["assistant"], "hi", model="m1")
    fake_log.say(["user"], "and?")
    bar = StatusBar(fake_log, stub_screen, [lambda s: seen.append(s) or "fine", lambda s: 1 / 0])
    assert strip(bar.line(fake_log.read(), 30)).strip() == "fine"
    (state,) = seen
    assert (state.last.content, state.holder, state.model, state.busy_since) == ("and?", None, "m1", None)


def test_with_context_renderers_the_last_message_is_the_last_they_leave(fake_log, stub_screen):
    seen = []
    fake_log.say(["user"], "kept")
    fake_log.say(["error"], "hidden")
    bar = StatusBar(fake_log, stub_screen, [seen.append], context=[lambda log: [e for e in log if e.tags != ["error"]]])
    bar.line(fake_log.read(), 30)
    assert seen[0].last.content == "kept"
    bar = StatusBar(fake_log, stub_screen, [seen.append], context=[lambda log: []])
    bar.line(fake_log.read(), 30)
    assert seen[1].last is None


def test_a_message_being_written_is_the_last_whatever_the_context_renderers_leave(fake_log, stub_screen):
    seen = []
    fake_log.say(["user"], "hi")
    fake_log.hold(Request(0, {"provider": "openai"}))
    fake_log.write(["assistant"], "stream")
    bar = StatusBar(fake_log, stub_screen, [seen.append], context=[lambda log: []])
    bar.line(fake_log.read(), 30)
    assert seen[0].last.content == "stream" and seen[0].last.streaming


def test_the_turn_is_timed_from_when_it_began_until_it_is_over(fake_log, stub_screen):
    clock = Clock()
    bar = StatusBar(fake_log, stub_screen, [], clock=clock)
    fake_log.ask()
    assert bar.state(fake_log.read()).busy_since == 100.0
    clock.now = 103.0
    fake_log.hold(Request(0, {"provider": "openai"}))
    state = bar.state(fake_log.read())
    assert state.busy_since == 100.0 and state.now == 103.0
    fake_log.hold(None)
    fake_log.say(["assistant"], "done")
    assert bar.state(fake_log.read()).busy_since is None


def test_a_key_goes_to_the_input_bar_with_the_focus(fake_log, stub_screen, layout):
    panes, tmux = layout(input="%3")
    StatusBar(fake_log, stub_screen, [], panes).on_key(b"h")
    assert tmux.sent == [("%3", b"h")] and tmux.focused == ["%3"]


async def test_it_draws_one_row_when_the_log_changes_and_stops_when_the_terminal_closes(fake_log, stub_screen):
    class Closing(type(stub_screen)):
        def read(self):
            if self.closed:
                raise EOFError
            return super().read()

    screen = Closing()
    screen.closed = False
    running = asyncio.create_task(StatusBar(fake_log, screen, [lambda s: s.last.content if s.last else "empty"]).run())
    fake_log.say(["note"], "news")
    for _ in range(100):
        if screen.drawn and "news" in screen.drawn[-1][0][0]:
            break
        await asyncio.sleep(0.005)
    assert len(screen.drawn[-1][0]) == 1 and "news" in screen.drawn[-1][0][0]
    screen.closed = True
    fake_log.say(["note"], "wake")
    await asyncio.wait_for(running, 1)


async def test_while_the_turn_runs_it_draws_again_each_second_and_otherwise_only_on_a_change(
    fake_log, stub_screen, monkeypatch
):
    from llvim.std.panels.status import bar as barmod

    monkeypatch.setattr(barmod, "TICK", 0.01)
    fake_log.ask()
    running = asyncio.create_task(StatusBar(fake_log, stub_screen, [lambda s: "x"]).run())
    await asyncio.sleep(0.1)
    busy = len(stub_screen.drawn)
    fake_log.say(["assistant"], "done")
    await asyncio.sleep(0.05)
    idle = len(stub_screen.drawn)
    await asyncio.sleep(0.1)
    running.cancel()
    await asyncio.gather(running, return_exceptions=True)
    assert busy > 3 and len(stub_screen.drawn) == idle
