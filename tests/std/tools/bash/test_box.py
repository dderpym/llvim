"""std/tools/bash/box.py: how a bash call looks, live while it runs and as its output after. The terminal is a stub."""

import json
import threading
import time
from typing import ClassVar

import pytest

from llvim.std.panels.logviewer.ansi import strip, width
from llvim.std.panels.logviewer.box import Host, group
from llvim.std.tmux import Snapshot, TmuxError
from llvim.std.tools.bash import BOX
from llvim.std.tools.bash import box as bash_box
from llvim.std.tools.bash.box import BashBox


class FakeEmbedded:
    """What ``llvim.std.tmux.Embedded`` is to the box: a screen to look at and keys to send."""

    made: ClassVar[list] = []
    looked: ClassVar[list] = []
    hidden = False

    def __init__(self, columns, rows):
        self.columns, self.rows, self.sent, self.resized = columns, rows, [], []
        self.shot = Snapshot(["$ make", "building…"] + [""] * (rows - 2), (9, 1), False, None)

    @classmethod
    def find(cls, control, option, value, columns, rows):
        if control is None:
            raise TmuxError("not in tmux")
        cls.looked.append((option, value))
        if cls.hidden:  # the runner has not started it yet
            return None
        cls.made.append(cls(columns, rows))
        return cls.made[-1]

    def snapshot(self):
        return self.shot

    def send(self, raw):
        self.sent.append(raw)

    def resize(self, columns, rows):
        self.columns, self.rows = columns, rows
        self.resized.append((columns, rows))


class LiveHost(Host):
    """A host that runs a box's update in a thread, as the viewer does."""

    live = True
    cols = 80

    def __init__(self, control="a connection"):
        self.connection, self.changes = control, threading.Event()

    def changed(self, box=None):
        self.changes.set()

    def control(self):
        if self.connection is None:
            raise TmuxError("not in tmux")
        return self.connection


@pytest.fixture(autouse=True)
def fake_terminals(monkeypatch):
    FakeEmbedded.made, FakeEmbedded.looked, FakeEmbedded.hidden = [], [], False
    monkeypatch.setattr(bash_box, "Embedded", FakeEmbedded)


def CALL(entry, interactive=False, user=False):
    arguments = json.dumps({"command": "make", "interactive": interactive})
    return entry(["tool_call", "bash"], arguments, call_id="1", **({"user": True} if user else {}))


def RESULT(entry, text="done\n", error=False):
    return entry(["tool_result", "bash"], text, call_id="1", error=error)


def wait_for(check, seconds=3):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.01)
    raise AssertionError("never happened")


def test_a_calls_messages_go_to_one_box_and_other_tools_and_messages_to_none(entry):
    messages = [
        CALL(entry), entry(["tool_start", "bash"], call_id="1"), entry(["tool_call", "echo"], "{}", call_id="2"), entry(["user"], "hi"),
        RESULT(entry),
    ]  # fmt: skip
    ((_, grouped),) = group(messages, [BOX]).values()
    assert [m.tags[0] for m in grouped] == ["tool_call", "tool_start", "tool_result"]


def test_a_call_nobody_has_picked_up_says_it_is_waiting(entry, stub_host):
    box = BashBox(stub_host, [CALL(entry)])
    rows = [strip(r) for r in box.rows(40)]
    assert rows[0].startswith("╭─ $ make") and "waiting for the runner" in rows[1] and rows[-1].startswith("╰")


def test_a_finished_call_shows_the_end_of_its_output_in_a_box_as_wide_as_the_screen(entry, stub_host):
    out = "\n".join(f"line {i}" for i in range(50))
    rows = BashBox(stub_host, [CALL(entry), RESULT(entry, out)]).rows(60)
    assert all(width(r) == 60 for r in rows) and len(rows) == 2 + 20  # twenty rows of output between the borders
    assert "rows above" in strip(rows[1]) and strip(rows[-2]).startswith("│ line 49")


def test_a_failed_call_is_drawn_in_red_and_a_long_command_is_cut_in_the_title(entry, stub_host):
    long = entry(["tool_call", "bash"], '{"command": "' + "echo " + "x" * 200 + '"}', call_id="1")
    ok = BashBox(stub_host, [long, RESULT(entry, "fine\n")]).rows(50)
    failed = BashBox(stub_host, [long, RESULT(entry, "bad\n[exit code 1]")]).rows(50)
    assert "…" in strip(failed[0]) and width(failed[0]) == 50
    assert "\x1b[38;5;203m" in failed[0] and "\x1b[38;5;203m" not in ok[0]


def test_while_the_command_runs_the_box_shows_its_terminal_and_says_when_it_changes(entry):
    host = LiveHost()
    box = BashBox(host, [CALL(entry)])
    assert host.changes.wait(3) and any("building" in strip(r) for r in box.rows(60))
    assert (FakeEmbedded.made[0].columns, FakeEmbedded.made[0].rows) == (
        76,
        14,
    )  # the box's inside, as wide as the screen allows
    box.close()


def test_only_a_command_that_asked_for_it_takes_the_keyboard(entry):
    plain, wants = LiveHost(), LiveHost()
    a, b = BashBox(plain, [CALL(entry)]), BashBox(wants, [CALL(entry, interactive=True)])
    wait_for(lambda: a.live is not None and b.live is not None)
    assert (
        not a.focusable
        and b.focusable
        and "click to type" in strip(b.rows(60)[-1])
        and "click to type" not in strip(a.rows(60)[-1])
    )
    a.close()
    b.close()


def test_the_keys_of_a_focused_box_go_to_the_terminal_and_its_cursor_is_where_the_terminals_is(entry):
    host = LiveHost()
    box = BashBox(host, [CALL(entry)])
    wait_for(lambda: box.live is not None)
    assert box.cursor() is None  # not focused: no cursor
    box.set_focus(True)
    box.key(b"ls\r")
    assert box.live.sent == [b"ls\r"] and box.cursor() == (2 + 9, 1 + 1)  # inside the border and its space
    assert "ctrl-] or click outside to leave" in strip(box.rows(60)[-1])
    box.close()


def test_a_call_the_user_made_asks_the_viewer_for_the_keyboard_once_its_terminal_is_up_and_one_the_model_made_does_not(
    entry,
):
    asked = []
    host = LiveHost()
    host.request_focus = asked.append
    box = BashBox(host, [CALL(entry, interactive=True, user=True)])
    wait_for(lambda: asked)
    assert asked == [box]
    plain = BashBox(host, [CALL(entry)])
    wait_for(lambda: plain.live is not None)
    assert asked == [box]
    box.close()
    plain.close()


def test_it_looks_for_the_terminal_of_its_call_until_the_runner_has_started_it(entry):
    FakeEmbedded.hidden = True
    host = LiveHost()
    box = BashBox(host, [CALL(entry)])
    wait_for(lambda: FakeEmbedded.looked)
    assert (
        FakeEmbedded.looked[0] == ("@llvim_call", "1")
        and box.live is None
        and "waiting for the runner" in strip(box.rows(60)[1])
    )
    FakeEmbedded.hidden = False
    wait_for(lambda: box.live is not None)
    box.close()
