"""std/tmux.py: Control and Embedded, programs in tmux. Needs a real tmux, and is the only module that tests it in depth."""

import time

import pytest

from llvim.std.tmux import Control, Embedded, TmuxError

pytestmark = pytest.mark.needs_tmux


@pytest.fixture
def control(tmux_server):
    tmux, socket = tmux_server
    c = Control(["-S", socket], "s")
    yield c
    c.close()


def tidy(transcript):
    """The transcript without the padding the terminal keeps: spaces at the ends of rows, blank rows under the last."""
    return "\n".join(line.rstrip() for line in transcript.split("\n")).strip("\n")


def wait_for(embedded, text, seconds=5):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        shot = embedded.snapshot()
        if any(text in line for line in shot.lines):
            return shot
        time.sleep(0.02)
    raise AssertionError(f"{text!r} never appeared: {embedded.snapshot().lines}")


def at_prompt(embedded):
    """Wait for the shell's prompt: keys typed while it redraws (after a resize) can be lost, as in any terminal."""
    end = time.monotonic() + 5
    while time.monotonic() < end:
        lines = [l for l in embedded.snapshot().lines if l.strip()]
        if lines and lines[-1].endswith("$"):
            return
        time.sleep(0.02)
    raise AssertionError("no prompt")


def test_control_returns_a_commands_output_and_an_error_for_one_that_fails(control):
    assert control.run("display-message -p hello").strip() == "hello"
    with pytest.raises(TmuxError):
        control.run("no-such-command")
    assert control.run("display-message -p again").strip() == "again"  # still in step after the error


def test_a_program_runs_where_it_is_told_takes_keys_and_shows_its_screen_with_colour(control, tmp_path):
    term = Embedded.start(control, "bash --norc", str(tmp_path), 60, 10)
    at_prompt(term)
    term.send(b"printf '\\033[32mgreen\\033[0m\\n'; basename \"$PWD\"\r")
    shot = wait_for(term, tmp_path.name)
    assert len(shot.lines) == 10 and any(l.startswith("\x1b[32mgreen") for l in shot.lines) and shot.cursor is not None and not shot.dead
    term.close()


def test_a_program_that_exits_leaves_its_screen_its_status_and_a_full_transcript(control, tmp_path):
    term = Embedded.start(control, "seq 1 40; printf 'x%.0s' $(seq 1 100); echo; exit 3", str(tmp_path), 30, 5)
    for _ in range(100):
        if (shot := term.snapshot()).dead:
            break
        time.sleep(0.02)
    assert shot.dead and shot.status == 3 and shot.cursor is None and "x" * 10 in shot.lines  # the last rows of what it printed (a 100-character line cut at 30)
    transcript = term.transcript()
    lines = tidy(transcript).split("\n")
    assert lines[:3] == ["1", "2", "3"] and lines[-1] == "x" * 100 and len(lines) == 41  # the history, with the wrapped line joined
    assert "Pane is dead" not in transcript and "Pane is dead" not in "".join(shot.lines)  # the pane is not left dead: tmux has no note to draw
    term.close()
    term.close()  # closing twice is fine


def test_a_second_party_can_attach_type_and_leave_without_ending_the_program(control, tmux_server, tmp_path):
    starter = Embedded.start(control, "bash --norc", str(tmp_path), 60, 10)
    at_prompt(starter)
    other = Control(["-S", tmux_server[1]], "s")
    try:
        looker = Embedded.attach(other, starter.pane, 50, 8)
        assert looker.pane == starter.pane and not looker.owner and starter.owner
        looker.send(b"echo from-the-looker\r")
        wait_for(starter, "from-the-looker")
        looker.close()  # it did not start it: nothing happens
        assert not starter.snapshot().dead
        with pytest.raises(TmuxError):
            Embedded.attach(other, "%999", 50, 8)
    finally:
        other.close()
    starter.close()


def test_a_program_is_found_by_the_option_it_was_started_with(control, tmux_server, tmp_path):
    term = Embedded.start(control, "sleep 30", str(tmp_path), 60, 10, {"@llvim_call": "call-7"})
    other = Control(["-S", tmux_server[1]], "s")
    try:
        found = Embedded.find(other, "@llvim_call", "call-7", 50, 8)
        assert found is not None and found.pane == term.pane and not found.owner
        assert Embedded.find(other, "@llvim_call", "call-8", 50, 8) is None
    finally:
        other.close()
    term.close()


COMMANDS = [
    ("echo a; echo b", ["a", "b"]),
    ("echo line1\necho line2", ["line1", "line2"]),
    ("cat <<EOF\nx 'q' \"d\" $HOME\\n\nEOF", None),
    ("echo 'it'\"'\"'s' \\\\ é 中", ["it's \\ é 中"]),
    ("echo " + "x" * 20_000 + " | wc -c", ["20001"]),
]


def test_any_command_text_runs_as_written_even_one_that_ends_at_once(control, tmp_path):
    """The command goes in a file, not through tmux's one-line command syntax: newlines, quotes and length are all text."""
    for command, printed in COMMANDS:
        term = Embedded.start(control, command, str(tmp_path), 100, 14)
        for _ in range(100):
            if (shot := term.snapshot()).dead:
                break
            time.sleep(0.02)
        assert shot.dead and shot.status == 0, command[:40]
        if printed is not None:
            assert tidy(term.transcript()).split("\n") == printed, command[:40]
        term.close()


def test_a_program_leaves_nothing_behind_when_it_is_closed(control, tmp_path):
    import tempfile
    from pathlib import Path

    term = Embedded.start(control, "true", str(tmp_path), 60, 10)
    files = term.files
    assert files is not None and files.parent == Path(tempfile.gettempdir()) and files.exists()
    term.close()
    assert not files.exists()
