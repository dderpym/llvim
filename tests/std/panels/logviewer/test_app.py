"""std/panels/logviewer/app.py: the viewer: scrolling, selecting and copying, and giving the keyboard to a box. The screen is
a stub."""

import asyncio

from llvim.std.panels.logviewer import ansi
from llvim.std.panels.logviewer.app import Viewer
from llvim.std.panels.logviewer.box import Box, alone, box
from llvim.std.panels.logviewer.screen import Key, Mouse


def viewer(fake_log, stub_screen, tmp_path, cols=40, rows=12, panes=None, renderers=()):
    stub_screen.cols, stub_screen.rows = cols, rows
    v = Viewer(fake_log, tmp_path, stub_screen, panes=panes, renderers=renderers)
    v.doc.sync(fake_log.read())
    v.frame()
    return v


def notes(fake_log, n):
    for i in range(n):
        fake_log.say(["note"], f"line {i}")


def rows_of(v):
    return [ansi.strip(r) for r in v.frame()[0]]


def drag(v, start, end):
    """Press at one cell, move to another, let go."""
    v.on_mouse(Mouse(0, *start, True))
    v.on_mouse(Mouse(32, *end, True))
    v.on_mouse(Mouse(0, *end, False))


def click(v, x, y):
    v.on_mouse(Mouse(0, x, y, True))
    v.on_mouse(Mouse(0, x, y, False))


# --- scrolling ---


def test_it_follows_the_end_of_the_log_and_makes_only_what_the_screen_needs(fake_log, stub_screen, tmp_path):
    notes(fake_log, 300)
    v = viewer(fake_log, stub_screen, tmp_path, rows=10)
    assert v.follow and any("line 299" in r for r in rows_of(v)) and sum(1 for s in v.doc.slots if s.box) <= 6


def test_scrolling_up_stops_following_and_scrolling_back_down_follows_again(fake_log, stub_screen, tmp_path):
    notes(fake_log, 60)
    v = viewer(fake_log, stub_screen, tmp_path, rows=10)
    end = rows_of(v)
    v.on_mouse(Mouse(64, 0, 0, True))  # a wheel notch up
    assert not v.follow and rows_of(v) != end
    for _ in range(100):
        v.on_mouse(Mouse(65, 0, 0, True))  # down, and past the end
    assert v.follow and rows_of(v) == end


# --- the keys it does not use go to the input bar ---


def test_a_key_the_viewer_does_not_use_is_typing_so_it_goes_to_the_input_bar_and_focus_goes_with_it(fake_log, stub_screen, tmp_path, layout):
    panes, tmux = layout(input="%3")
    v = viewer(fake_log, stub_screen, tmp_path, panes=panes)
    assert v.on_key(Key(b"h")) is True and v.on_key(Key(b"\x03")) is True  # ctrl-c too: it is the bar's, to clear its line
    assert tmux.sent == [("%3", b"h"), ("%3", b"\x03")] and tmux.focused == ["%3", "%3"]


def test_the_keys_the_viewer_uses_itself_are_not_passed_on(fake_log, stub_screen, tmp_path, layout):
    panes, tmux = layout(input="%3")
    notes(fake_log, 40)
    v = viewer(fake_log, stub_screen, tmp_path, rows=8, panes=panes)
    end = rows_of(v)
    for raw in (b"\x1b[A", b"\x1b[B", b"\x1b[5~", b"\x1b[6~", b"\x1b[H", b"\x1b[F"):  # up, down, page up and down, home, end
        v.on_key(Key(raw))
    assert rows_of(v) == end and tmux.sent == [] and tmux.focused == []  # up, down, page up and down, home, end: back where it began


def test_escape_lets_go_of_a_selection_here_and_is_not_passed_on(fake_log, stub_screen, tmp_path, layout):
    panes, tmux = layout(input="%3")
    fake_log.say(["note"], "some text")
    v = viewer(fake_log, stub_screen, tmp_path, panes=panes)
    drag(v, (0, rows_of(v).index("some text")), (3, rows_of(v).index("some text")))
    v.on_key(Key(b"\x1b"))
    assert v.selection is None and tmux.sent == []


def test_a_viewer_on_its_own_has_nowhere_to_send_keys_and_ctrl_c_ends_it(fake_log, stub_screen, tmp_path, layout):
    panes, tmux = layout()  # no input bar in this layout
    v = viewer(fake_log, stub_screen, tmp_path, panes=panes)
    assert v.on_key(Key(b"x")) is True and v.on_key(Key(b"\x03")) is False and tmux.sent == []


# --- selecting and copying ---


def test_a_drag_copies_the_text_it_covers_and_highlights_it(fake_log, stub_screen, tmp_path):
    fake_log.say(["note"], "alpha beta")
    fake_log.say(["note"], "gamma delta")
    v = viewer(fake_log, stub_screen, tmp_path)
    rows = rows_of(v)
    first, second = rows.index("alpha beta"), rows.index("gamma delta")
    drag(v, (6, first), (4, second))  # from "beta" to the fifth letter of "gamma delta"
    assert stub_screen.copied == ["beta\n\n\nnote\ngamma"]
    lit = [ansi.strip(r) for r in v.frame()[0] if "\x1b[7m" in r]
    assert "alpha beta" in lit and "gamma delta" in lit


def test_a_line_that_was_cut_to_fit_is_copied_as_one_line_with_its_spaces(fake_log, stub_screen, tmp_path):
    long = ("word " * 20).strip()
    fake_log.say(["note"], long)
    v = viewer(fake_log, stub_screen, tmp_path, cols=30)
    first = next(i for i, r in enumerate(rows_of(v)) if r.startswith("word"))
    drag(v, (0, first), (29, first + 3))
    assert stub_screen.copied[0] == long[: len(stub_screen.copied[0])].rstrip() and "\n" not in stub_screen.copied[0]


def test_a_selection_stays_on_its_text_when_the_screen_scrolls(fake_log, stub_screen, tmp_path):
    notes(fake_log, 30)
    v = viewer(fake_log, stub_screen, tmp_path, rows=8)
    y = next(i for i, r in enumerate(rows_of(v)) if r.startswith("line 29"))
    drag(v, (0, y), (5, y))
    v.scroll(-9)
    assert v.selected_text() == "line 2" and not any("\x1b[7m" in r for r in v.frame()[0])  # still that text, no longer on the screen


def test_a_click_is_not_a_selection_and_a_new_press_or_escape_lets_go_of_one(fake_log, stub_screen, tmp_path):
    fake_log.say(["note"], "some text")
    v = viewer(fake_log, stub_screen, tmp_path)
    row = rows_of(v).index("some text")
    click(v, 2, row)
    assert stub_screen.copied == [] and v.selection is None
    drag(v, (0, row), (3, row))
    assert stub_screen.copied == ["some"] and v.selection is not None
    v.on_mouse(Mouse(0, 0, row, True))
    assert v.selection is None
    drag(v, (0, row), (3, row))
    v.on_key(Key(b"\x1b"))
    assert v.selection is None


def test_a_box_that_draws_itself_is_copied_without_its_frame(fake_log, stub_screen, tmp_path):
    @box(lambda m: alone(m) if m.tags == ["framed"] else None)
    class Framed(Box):
        def __init__(self, host, messages):
            super().__init__(host, messages)
            host.layout(self, lambda cols: ["╭─ title ─╮", "│ inside  │", "╰─────────╯"])

    fake_log.say(["framed"])
    v = viewer(fake_log, stub_screen, tmp_path, renderers=[Framed])
    rows = rows_of(v)
    drag(v, (0, rows.index("╭─ title ─╮")), (10, rows.index("╰─────────╯")))
    assert stub_screen.copied[0] == "title\ninside"


# --- giving the keyboard to a box ---


class Takes(Box):
    """A box that takes the keyboard, and notes what it is given."""

    keys: list = []

    def __init__(self, host, messages):
        super().__init__(host, messages)
        self.lines = ["TAKES"]
        self.got_focus = []
        host.focusable(self, True)
        host.on_focus(self, self.got_focus.append)
        host.on_key(self, lambda raw: Takes.keys.append(raw))
        host.cursor(self, lambda: (3, 0))


def with_taker(fake_log, stub_screen, tmp_path):
    Takes.keys = []
    fake_log.say(["note"], "above")
    fake_log.say(["takes"], "x")
    v = viewer(fake_log, stub_screen, tmp_path, renderers=[box(lambda m: alone(m) if m.tags == ["takes"] else None)(Takes)])
    return v, rows_of(v).index("TAKES")


def test_clicking_a_box_that_takes_the_keyboard_gives_it_the_keys_until_ctrl_bracket(fake_log, stub_screen, tmp_path):
    v, y = with_taker(fake_log, stub_screen, tmp_path)
    click(v, 1, y)
    assert v.focus is not None and v.focus.box.got_focus == [True]
    v.on_key(Key(b"ls\r"))
    v.on_key(Key(b"\x03"))  # ctrl-c goes to the box, it does not quit the viewer
    assert Takes.keys == [b"ls\r", b"\x03"]
    v.on_key(Key(b"\x1d"))  # ctrl-]: the way out
    assert v.focus is None and v.on_key(Key(b"\x03")) is False


def test_a_box_that_asks_for_the_keyboard_gets_it_and_the_view_goes_to_the_end(fake_log, stub_screen, tmp_path):
    v, y = with_taker(fake_log, stub_screen, tmp_path)
    taker = next(s.box for s in v.doc.slots if isinstance(s.box, Takes))
    v.host.request_focus(taker)
    v.grant_focus()
    assert v.focus is not None and v.focus.box is taker and taker.got_focus == [True] and v.follow


def test_a_click_on_a_box_that_takes_clicks_tells_it_without_giving_it_the_keyboard(fake_log, stub_screen, tmp_path):
    v, y = with_taker(fake_log, stub_screen, tmp_path)
    clicked = []
    taker = next(s.box for s in v.doc.slots if isinstance(s.box, Takes))
    taker.hooks.focusable = False
    taker.hooks.on_click = lambda: clicked.append(1)
    click(v, 1, y)
    assert clicked == [1] and v.focus is None


def test_a_box_whose_hook_raises_is_marked_failed_and_the_viewer_goes_on(fake_log, stub_screen, tmp_path):
    v, y = with_taker(fake_log, stub_screen, tmp_path)
    click(v, 1, y)
    v.focus.box.hooks.on_key = lambda raw: 1 / 0
    v.on_key(Key(b"x"))
    assert isinstance(v.focus.box.error, ZeroDivisionError) and v.doc.replace_failed()


# --- the loop ---


async def test_it_draws_when_the_log_changes_and_ends_on_ctrl_c_when_alone(fake_log, stub_screen, tmp_path, layout):
    panes, _ = layout()
    running = asyncio.create_task(Viewer(fake_log, tmp_path, stub_screen, panes=panes).run())
    fake_log.say(["note"], "news")
    for _ in range(100):
        if any("news" in ansi.strip(r) for r in (stub_screen.drawn[-1][0] if stub_screen.drawn else [])):
            break
        await asyncio.sleep(0.005)
    assert any("news" in ansi.strip(r) for r in stub_screen.drawn[-1][0])
    stub_screen.events.append(Key(b"\x03"))
    fake_log.say(["note"], "wakes it")
    await asyncio.wait_for(running, 2)
