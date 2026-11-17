"""std/tools/bash/shared.py: a terminal kept past its call, which the model and the user take turns at. Needs a real tmux."""

import asyncio
import time

import pytest

from llvim.std.tmux import Control, Embedded
from llvim.std.tools.bash import shared, terminal

pytestmark = pytest.mark.needs_tmux

SETTLE = 0.15


@pytest.fixture
def control(tmux_server, monkeypatch):
    monkeypatch.setattr(terminal, "GRACE", 0.3)
    c = Control(["-S", tmux_server[1]], "s")
    yield c
    shared.close_all()
    c.close()


@pytest.fixture
def start(control, tmp_path):
    """`await start(command, timeout=5)`: the command on a terminal kept as "t1", in the project folder `tmp_path`."""

    async def go(command, timeout=5.0, id="t1"):
        return await shared.start(command, tmp_path, id, timeout, SETTLE, control)

    return go


def owner(control, id):
    return Embedded.find(control, terminal.CALL_OPTION, id, 80, 10).value(shared.OWNER)


async def test_it_returns_once_the_screen_is_still_and_the_program_keeps_running(start):
    began = time.monotonic()
    seen = await start("printf 'name? '; read name; echo hi $name")
    assert time.monotonic() - began < 3 and seen.output == "name? " and seen.running and not seen.still_changing
    assert shared.is_kept("t1")


async def test_typed_keys_reach_the_program_and_a_newline_is_enter(start):
    await start("bash --norc")
    seen = await shared.type_keys("t1", "echo $((6 * 7))\n", 5, SETTLE)
    assert "42" in seen.output.split("\n") and seen.running


async def test_a_program_that_exits_says_how_and_is_closed(start, control):
    await start("read x; exit $x")
    seen = await shared.type_keys("t1", "4\n", 5, SETTLE)
    assert seen.status == 4 and not seen.running and not shared.is_kept("t1")
    assert Embedded.find(control, terminal.CALL_OPTION, "t1", 80, 10) is None
    with pytest.raises(shared.Closed):
        await shared.type_keys("t1", "", 1, SETTLE)


async def test_a_screen_that_never_settles_returns_at_the_timeout_and_is_left_running(start):
    began = time.monotonic()
    seen = await start("while true; do date +%N; sleep 0.05; done", timeout=0.4)
    assert time.monotonic() - began < 3 and seen.still_changing and seen.running


async def test_each_look_starts_on_the_line_the_cursor_was_on_at_the_last(start):
    seen = await start("bash --norc")
    assert seen.output.endswith("$ ")
    for n in range(3):  # enough to scroll the screen, so rows in history are counted too
        prompt, *printed, next_prompt = (await shared.type_keys("t1", "seq 1 6\n", 5, SETTLE)).output.split("\n")
        assert (
            prompt.endswith("$ seq 1 6") and printed == ["1", "2", "3", "4", "5", "6"] and next_prompt.endswith("$ ")
        ), n


async def test_a_full_screen_program_is_given_its_whole_screen_each_look(start):
    await start("printf 'top line\\n'; tput smcup; printf 'drawn\\n'; read x")
    for look in range(2):
        output = (await shared.type_keys("t1", "", 5, SETTLE)).output
        assert output.strip() == "drawn" and "top line" not in output, look


async def test_handed_to_the_user_it_waits_until_they_hand_it_back(start, control):
    await start("bash --norc")
    handing = asyncio.ensure_future(shared.hand_to_user("t1", 10))
    await asyncio.sleep(0.15)
    assert not handing.done() and owner(control, "t1") == shared.USER
    view = Embedded.find(control, terminal.CALL_OPTION, "t1", 80, 10)  # the viewer's box, as the user types
    view.send(b"echo typed-by-the-user\r")
    await asyncio.sleep(0.15)
    view.set_option(shared.OWNER, shared.AGENT)
    seen = await handing
    assert (
        seen.handed_back
        and seen.running
        and "typed-by-the-user" in seen.output
        and owner(control, "t1") == shared.AGENT
    )


async def test_a_user_who_never_hands_it_back_loses_it_when_their_time_runs_out(start, control):
    await start("bash --norc")
    seen = await shared.hand_to_user("t1", 0.15)
    assert not seen.handed_back and seen.running and owner(control, "t1") == shared.AGENT


async def test_cancelled_while_the_user_has_it_it_is_the_models_again(start, control):
    await start("bash --norc")
    handing = asyncio.ensure_future(shared.hand_to_user("t1", 10))
    await asyncio.sleep(0.2)
    handing.cancel()
    seen = await handing
    assert seen.cancelled and seen.running and owner(control, "t1") == shared.AGENT


async def test_closing_stops_it_with_ctrl_c_and_closes_one_that_ignores_that(start, control):
    await start("sleep 30", id="polite")
    await start("trap '' INT; echo stubborn; sleep 30", id="stubborn")
    began = time.monotonic()
    polite, stubborn = await shared.close("polite"), await shared.close("stubborn")
    assert time.monotonic() - began < 3 and not polite.running and polite.status == 130
    assert (
        not stubborn.running and stubborn.status is None and "stubborn" not in stubborn.output
    )  # the model saw that already
    assert not shared.is_kept("polite") and not shared.is_kept("stubborn")


async def test_a_terminal_whose_pane_was_killed_is_forgotten(start, control):
    await start("sleep 30")
    control.run(f"kill-pane -t {Embedded.find(control, terminal.CALL_OPTION, 't1', 80, 10).pane}")
    with pytest.raises(shared.Closed):
        await shared.type_keys("t1", "x", 1, SETTLE)
    assert not shared.is_kept("t1")


async def test_close_all_leaves_no_terminal_behind(start, control):
    await start("sleep 30", id="a")
    await start("sleep 30", id="b")
    shared.close_all()
    assert not shared.is_kept("a") and Embedded.find(control, terminal.CALL_OPTION, "a", 80, 10) is None
    assert Embedded.find(control, terminal.CALL_OPTION, "b", 80, 10) is None
