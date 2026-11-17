"""std/tools/bash/terminal.py: a command in a hidden tmux window tagged with its call. Needs a real tmux."""

import asyncio
import time

import pytest

from llvim.std.tmux import Control, Embedded
from llvim.std.tools.bash import terminal

pytestmark = pytest.mark.needs_tmux


@pytest.fixture
def run(tmux_server, tmp_path, monkeypatch):
    """`run(command, timeout=10, interactive=False)`: the command run in a real terminal in the project folder `tmp_path`."""
    monkeypatch.setattr(terminal, "GRACE", 0.5)
    control = Control(["-S", tmux_server[1]], "s")

    def go(command, timeout=10.0, interactive=False):
        return asyncio.run(terminal.run(command, tmp_path, "c1", timeout, interactive, control))

    yield go
    control.close()


def test_both_streams_come_back_in_order_with_the_exit_status_in_the_project_folder(run, tmp_path):
    ran = run("echo out; echo err >&2; pwd; exit 3")
    assert ran.output == f"out\nerr\n{tmp_path.resolve()}\n" and ran.status == 3


def test_what_a_command_nobody_types_into_wrote_comes_back_byte_for_byte(run):
    assert run(r"printf '\n  a\tb  \r\n\033[1mbold\033[0m no newline'").output == "\n  a\tb  \r\n\x1b[1mbold\x1b[0m no newline"


def test_nothing_waits_for_input_and_only_an_interactive_command_is_on_the_terminal(run):
    assert run("cat; echo done").output == "done\n"  # its input is closed, so cat ends at once
    assert run("test -t 1 || echo not a tty").output == "not a tty\n"
    assert run("echo $PAGER $GIT_PAGER").output == "cat cat\n"
    assert run("test -t 0 && test -t 1 && echo tty", interactive=True).output == "tty"  # what sudo needs


def test_an_interactive_command_returns_its_screen_without_the_empty_rows_under_it(run):
    assert run(r"printf 'abc\rX\n'", interactive=True).output == "Xbc"


def test_something_left_running_in_the_background_does_not_hold_the_call(run):
    start = time.monotonic()
    ran = run("echo hi; sleep 30 & echo done")
    assert time.monotonic() - start < 5 and ran.output == "hi\ndone\n" and ran.status == 0


def test_a_command_still_running_at_its_timeout_gets_ctrl_c_and_says_what_it_had_printed(run):
    start = time.monotonic()
    ran = run("echo started; sleep 30", timeout=0.5)
    assert time.monotonic() - start < 5 and ran.timed_out and ran.status is None and "started" in ran.output


def test_a_command_that_ignores_ctrl_c_is_closed_on(run):
    start = time.monotonic()
    ran = run("trap '' INT; echo stubborn; sleep 30", timeout=0.3)
    assert time.monotonic() - start < 5 and ran.timed_out and "stubborn" in ran.output


def test_cancelled_it_stops_the_command_and_still_returns_what_it_printed(tmux_server, tmp_path):
    control = Control(["-S", tmux_server[1]], "s")

    async def cancel_soon():
        running = asyncio.ensure_future(terminal.run("echo going; sleep 30", tmp_path, "c1", 30, False, control))
        await asyncio.sleep(0.5)
        running.cancel()
        return await running

    try:
        start = time.monotonic()
        ran = asyncio.run(cancel_soon())
    finally:
        control.close()
    assert time.monotonic() - start < 5 and ran.cancelled and "going" in ran.output


def test_while_it_runs_its_pane_is_found_by_its_call_and_once_it_is_done_the_pane_is_gone(tmux_server, tmp_path):
    control = Control(["-S", tmux_server[1]], "s")

    async def look_while_running():
        running = asyncio.ensure_future(terminal.run("sleep 1", tmp_path, "c7", 10, False, control))
        await asyncio.sleep(0.3)
        found = Embedded.find(control, terminal.CALL_OPTION, "c7", 80, 10)
        await running
        return found

    try:
        assert asyncio.run(look_while_running()) is not None
        assert Embedded.find(control, terminal.CALL_OPTION, "c7", 80, 10) is None
    finally:
        control.close()


def test_on_the_terminal_long_lines_are_joined_and_the_history_is_kept(run):
    lines = run("seq 1 300; printf 'y%.0s' $(seq 1 400); echo", interactive=True).output.split("\n")
    assert lines[0] == "1" and lines[299] == "300" and lines[300] == "y" * 400


def test_the_file_the_output_went_to_is_removed(run, tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    run("echo x")
    assert not list(tmp_path.glob("llvim-bash-*"))
