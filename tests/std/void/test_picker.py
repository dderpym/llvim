"""std/void/picker.py: the picker lists a log's turns, and voids and restores what is chosen, with the log held while it is
open. The log and the screen are stubs."""

import asyncio
import contextlib
import os

import pytest

from llvim.core import Request
from llvim.std.conversation import entries
from llvim.std.panels.keys import Key
from llvim.std.panels.logviewer.ansi import strip, width
from llvim.std.void.picker import REQUEST, WAITING, Picker, pick, set_void

UP, DOWN, TAB, LEFT, ENTER, ESC = b"\x1b[A", b"\x1b[B", b"\t", b"\x1b[D", b"\r", b"\x1b"


@pytest.fixture
def log(fake_log):
    """Three turns: `one` and its reply; `two`, a reply, a bash call with its start and result, a last reply; `three` and its."""
    fake_log.ask("one")
    fake_log.say(["assistant"], "reply one")
    fake_log.ask("two")
    fake_log.say(["assistant"], "I'll look")
    fake_log.say(["tool_call", "bash"], '{"command": "ls"}', call_id="a")
    fake_log.say(["cue", "tools"])
    fake_log.say(["tool_start", "bash"], call_id="a")
    fake_log.say(["tool_result", "bash"], "a.txt", call_id="a")
    fake_log.say(["cue", "generate"])
    fake_log.say(["assistant"], "done")
    fake_log.ask("three")
    fake_log.say(["assistant"], "reply three")
    return fake_log


@pytest.fixture
def keyboard(stub_screen):
    """The stub screen with a pipe for a keyboard, so a program waiting on its fds wakes: `keyboard.press(b"v", ...)`."""
    read, write = os.pipe()
    os.set_blocking(read, False)

    def press(*keys):
        stub_screen.events = [Key(key) for key in keys]
        os.write(write, b"x")

    def take():
        with contextlib.suppress(BlockingIOError):
            os.read(read, 4096)
        events, stub_screen.events = stub_screen.events, []
        return events

    stub_screen.fds, stub_screen.read, stub_screen.press = lambda: [read], take, press
    yield stub_screen
    os.close(read)
    os.close(write)


def voided(log):
    """The text of each voided message, with `cue` for a voided cue and the tool's tag for a call's messages."""
    return [e.content or e.tags[0] for e in entries(log.read()) if "void" in e.tags]


async def opened(log, screen):
    """The picker, holding the log as `pick` hands it one."""
    return Picker(log, screen, await log.claim(REQUEST))


async def press(picker, *keys):
    for key in keys:
        await picker.on_key(key)


def shown(picker, cols=60, height=12):
    return [strip(row).rstrip() for row in picker.render(cols, height)]


async def test_it_lists_the_turns_numbered_and_opens_on_the_last(log, stub_screen):
    picker = await opened(log, stub_screen)
    assert shown(picker)[1:] == [" ▸   1  one", " ▸   2  two", " ▸   3  three"]
    assert picker.chosen().number == 3


async def test_up_and_down_move_the_choice_and_stop_at_the_ends(log, stub_screen):
    picker = await opened(log, stub_screen)
    await press(picker, DOWN)
    assert picker.chosen().number == 3
    await press(picker, UP, UP, UP, UP)
    assert picker.chosen().number == 1


async def test_enter_voids_the_chosen_turn_and_everything_after_it_cues_too_and_closes(log, stub_screen):
    picker = await opened(log, stub_screen)
    await press(picker, UP, ENTER)
    assert (
        picker.done
        and len(voided(log)) == 12
        and [e.content for e in entries(log.read()) if "void" not in e.tags][::2] == ["one", "reply one"]
    )
    assert not log.read().uncommitted


async def test_v_voids_only_the_chosen_turn_and_stays_open_and_v_again_restores_it(log, stub_screen):
    picker = await opened(log, stub_screen)
    before = log.read().messages
    await press(picker, UP, b"v")
    assert not picker.done and voided(log) == [
        "two",
        "cue",
        "I'll look",
        '{"command": "ls"}',
        "cue",
        "tool_start",
        "a.txt",
        "cue",
        "done",
    ]
    assert shown(picker)[2].endswith("VOID") and not shown(picker)[3].endswith("VOID")
    await press(picker, b"v")
    assert log.read().messages == before


async def test_tab_opens_a_turn_into_its_elements_and_left_shuts_it(log, stub_screen):
    picker = await opened(log, stub_screen)
    await press(picker, UP, TAB)
    assert shown(picker)[2:7] == [
        " ▾   2  two", "          user  two", "          assistant  I'll look", '          tool_call bash  {"command": "ls"}',
        "          assistant  done",
    ]  # fmt: skip
    await press(picker, DOWN, DOWN, LEFT)
    assert shown(picker)[1:] == [" ▸   1  one", " ▸   2  two", " ▸   3  three"] and picker.chosen().element is None


async def test_v_on_an_element_voids_it_alone_a_call_with_its_start_and_result_and_the_turn_says_in_part(
    log, stub_screen
):
    picker = await opened(log, stub_screen)
    await press(picker, UP, TAB, DOWN, DOWN, DOWN, b"v")
    assert voided(log) == ['{"command": "ls"}', "cue", "tool_start", "a.txt", "cue"]
    rows = shown(picker)
    assert rows[2].endswith("◐") and rows[5].endswith("VOID") and not rows[4].endswith("VOID")


async def test_enter_on_an_element_voids_from_it_on(log, stub_screen):
    picker = await opened(log, stub_screen)
    await press(picker, UP, TAB, DOWN, DOWN, ENTER)
    assert voided(log)[0] == "I'll look" and voided(log)[-1] == "reply three" and "two" not in voided(log)


async def test_enter_does_not_restore_what_is_already_voided(log, stub_screen):
    picker = await opened(log, stub_screen)
    await press(picker, b"v", UP, ENTER)
    assert len(voided(log)) == 12


async def test_each_void_is_committed_as_it_is_made(log, stub_screen):
    picker = await opened(log, stub_screen)
    commits = len(log.authors)
    await press(picker, b"v", UP, b"v")
    assert len(log.authors) == commits + 2 and not log.read().uncommitted


async def test_set_void_skips_messages_that_are_gone_or_have_no_tags(fake_log):
    fake_log.say(["user"], "hi")
    writer = await fake_log.claim(REQUEST)
    writer.append(b"no tags here")
    await set_void(writer, fake_log, [0, 1, 99], True)
    assert voided(fake_log) == ["hi"]


async def test_every_row_is_as_wide_as_the_screen_and_the_chosen_one_stays_in_sight(fake_log, stub_screen):
    for n in range(30):
        fake_log.say(["user"], f"message {n} " + "x" * 80)
    picker = await opened(fake_log, stub_screen)
    rows = picker.render(40, 6)
    assert len(rows) == 6 and all(width(row) == 40 for row in rows)
    assert "30  message 29" in strip(rows[-1]) and "\x1b[7m" in rows[-1]


async def test_an_empty_log_says_so(fake_log, stub_screen):
    assert shown(await opened(fake_log, stub_screen))[1] == "the log is empty"


async def test_running_it_takes_keys_from_the_screen_and_ends_on_escape(log, stub_screen):
    picker = await opened(log, stub_screen)
    stub_screen.events = [Key(b"v"), Key(ESC)]
    picker._poke.set()
    await asyncio.wait_for(picker.run(), 1)
    assert voided(log) == ["three", "cue", "reply three"] and stub_screen.drawn


async def test_pick_holds_the_log_for_as_long_as_the_picker_is_open_and_lets_go_when_it_closes(log, keyboard):
    picking = asyncio.ensure_future(pick(log, keyboard))
    while log.holder() is None:
        await asyncio.sleep(0.005)
    await asyncio.sleep(0.02)
    assert log.holder() == REQUEST and not picking.done()  # nobody else writes while you choose
    keyboard.press(ESC)
    await asyncio.wait_for(picking, 1)
    assert log.holder() is None


async def test_while_someone_else_holds_the_log_pick_says_it_waits_and_opens_once_it_is_free(log, keyboard):
    log.hold(Request(0, {"provider": "openai"}))
    picking = asyncio.ensure_future(pick(log, keyboard))
    await asyncio.sleep(0.02)
    assert WAITING.startswith(strip(keyboard.drawn[-1][0][0]).strip()[:30]) and len(keyboard.drawn[-1][0]) == 1
    log.hold(None)
    while len(keyboard.drawn[-1][0]) == 1:
        await asyncio.sleep(0.005)
    assert log.holder() == REQUEST
    keyboard.press(ESC)
    await asyncio.wait_for(picking, 1)


async def test_a_closing_key_gives_up_the_wait_and_takes_the_claim_back(log, keyboard):
    log.hold(Request(0, {"provider": "openai"}))
    picking = asyncio.ensure_future(pick(log, keyboard))
    await asyncio.sleep(0.02)
    keyboard.press(ESC)
    await asyncio.wait_for(picking, 1)
    assert log.queue() == [Request(0, {"provider": "openai"})] and voided(log) == []


async def test_given_an_offer_pick_adopts_that_claim_instead_of_making_one(log, keyboard):
    giver = await log.claim(REQUEST)
    offer = giver.offer()
    picking = asyncio.ensure_future(pick(log, keyboard, offer.address))
    await asyncio.wait_for(offer.taken(), 1)
    assert log.claims == [REQUEST] and log.holder() == REQUEST  # one claim, never let go
    await asyncio.sleep(0.02)
    keyboard.press(b"v", ESC)
    await asyncio.wait_for(picking, 1)
    assert voided(log) == ["three", "cue", "reply three"] and log.holder() is None
