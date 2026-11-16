"""std/panels/keys.py: a key becomes a decision, and a redirect moves it to another panel by name."""

import subprocess
import time

import pytest

from llvim.std.panels.keys import Key, Mouse, Outcome, Panes, Redirect, over, parse, route


# --- deciding ---


def test_input_is_split_into_keys_and_mouse_events_and_an_escape_sequence_is_one_key():
    events = parse(b"a\x1b[A\x1b[<64;10;5M\x1b[5~\xc3\xa9\x1b[<0;3;4m\x1bx\x03\x1b[<32;7;8M")
    assert events == [
        Key(b"a"), Key(b"\x1b[A"), Mouse(64, 9, 4, True), Key(b"\x1b[5~"), Key("é".encode()),
        Mouse(0, 2, 3, False), Key(b"\x1bx"), Key(b"\x03"), Mouse(32, 6, 7, True),
    ]  # fmt: skip
    assert b"".join(e.raw for e in events if isinstance(e, Key)) == b"a\x1b[A\x1b[5~\xc3\xa9\x1bx\x03"  # the bytes, to pass on unchanged


def test_the_first_handler_that_does_not_pass_decides():
    asked = []

    def passes(raw):
        asked.append("a")
        return Outcome.PASS

    def takes(raw):
        asked.append("b")
        return Outcome.HANDLED

    assert route(b"x", passes, takes, lambda raw: 1 / 0) is Outcome.HANDLED and asked == ["a", "b"]  # the third was never asked


def test_a_key_nobody_wants_passes_and_a_redirect_is_a_decision_too():
    assert route(b"x") is Outcome.PASS and route(b"x", lambda raw: Outcome.PASS) is Outcome.PASS
    assert route(b"x", lambda raw: Redirect("input", raw)) == Redirect("input", b"x", focus=True)


# --- finding panels ---


def test_a_panel_is_found_by_name_from_the_options_the_start_script_set_and_remembered(layout):
    p, tmux = layout(input="%3")
    assert p.id("input") == "%3" and p.id("input") == "%3" and p.known("input")
    assert tmux.commands == [["show-options", "-wqv", "-t", "%1", "@llvim_pane_input"]]  # asked once, for this panel's window


def test_a_panel_that_was_never_recorded_is_unknown_and_so_is_this_panel_itself(layout):
    p, _ = layout(input="%3")
    assert p.id("viewer") is None and not p.known("viewer")
    own, _ = layout(input="%1")  # the panel to redirect to is this one
    assert own.id("input") == "%1" and not own.known("input")


def test_outside_a_tmux_layout_no_panel_is_known_and_nothing_is_asked(layout):
    _, tmux = layout(input="%3")
    p = Panes(tmux, here="")
    assert p.id("input") is None and not p.known("input") and p.apply(Redirect("input", b"x")) is False and tmux.commands == []


# --- redirecting ---


def test_a_redirect_sends_the_keys_as_hex_and_moves_focus(layout):
    p, tmux = layout(input="%3")
    assert p.apply(Redirect("input", "é\r".encode())) is True
    assert tmux.commands[1:] == [["send-keys", "-t", "%3", "-H", "c3", "a9", "0d"], ["select-pane", "-t", "%3"]]


def test_a_redirect_may_only_move_focus_or_only_send(layout):
    p, tmux = layout(input="%3")
    p.apply(Redirect("input"))
    p.apply(Redirect("input", b"x", focus=False))
    assert tmux.commands[1:] == [["select-pane", "-t", "%3"], ["send-keys", "-t", "%3", "-H", "78"]]


def test_a_redirect_that_tmux_refuses_is_reported_and_the_pane_is_looked_up_again_next_time(layout):
    _, tmux = layout(input="%3")

    def refuses(args):
        if args[0] in ("send-keys", "select-pane"):
            raise RuntimeError("no such pane")
        return tmux(args)

    flaky = Panes(refuses, here="%1")
    assert flaky.apply(Redirect("input", b"x")) is False
    tmux.ids = {"input": "%4"}  # the pane was replaced
    assert flaky.id("input") == "%4"


def test_over_runs_commands_on_a_control_connection_quoting_them():
    seen = []

    class Control:
        def run(self, command):
            seen.append(command)
            return "out"

    assert over(Control())(["send-keys", "-t", "%3", "-H", "61"]) == "out" and over(lambda: Control())(["a b"]) == "out"
    assert seen == ["send-keys -t %3 -H 61", "'a b'"]


# --- the real thing ---


@pytest.mark.needs_tmux
def test_a_redirect_through_a_real_tmux_puts_the_keys_in_the_other_pane_and_focus_with_them(tmux_server):
    tmux, _ = tmux_server
    here = tmux("display-message", "-p", "-t", "s", "#{pane_id}").strip()
    other = tmux("split-window", "-t", "s", "-P", "-F", "#{pane_id}", "cat").strip()
    tmux("select-pane", "-t", here)
    tmux("set-option", "-w", "-t", "s", "@llvim_pane_input", other)
    real = Panes(lambda args: subprocess.run(["tmux", "-L", tmux.sock, *args], capture_output=True, text=True).stdout, here=here)
    assert real.apply(Redirect("input", b"hello")) is True
    for _ in range(50):
        if "hello" in tmux("capture-pane", "-p", "-t", other):
            break
        time.sleep(0.02)
    assert "hello" in tmux("capture-pane", "-p", "-t", other) and tmux("display-message", "-p", "-t", "s", "#{pane_id}").strip() == other
