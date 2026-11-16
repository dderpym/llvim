"""std/panels/input/bar.py: what each key does, and sending what was typed."""

import asyncio
import getpass
from contextlib import aclosing

import pytest

from llvim.core import Request
from llvim.std.conversation import encode, entries
from llvim.std.cues import GENERATE, cue, cued
from llvim.std.panels.input import STANDARD
from llvim.std.panels.input import bar as barmod
from llvim.std.panels.input.bar import Bar


class StubGrowth:
    def __init__(self):
        self.wanted = []

    def want(self, extra):
        self.wanted.append(extra)


@pytest.fixture
def make(fake_log, stub_screen, layout):
    def build(**kw):
        panes, tmux = layout(viewer="%2")
        ended = []
        kw.setdefault("quit", lambda: ended.append(1))
        kw.setdefault("commands", STANDARD)
        return Bar(fake_log, stub_screen, panes, StubGrowth(), **kw), tmux, ended

    return build


def type_(bar, text):
    for ch in text:
        bar.on_key(ch.encode())


def said(log):
    return [(e.tags, e.content) for e in entries(log.read())]


async def settle(bar):
    await asyncio.gather(*bar._tasks)


async def recorder(got, log, text):
    got.append(text)


# --- sending ---


async def test_a_message_is_committed_as_the_users_with_a_cue_for_the_model(fake_log):
    await barmod.send(fake_log, "hello there")
    assert said(fake_log) == [(["user"], "hello there"), (["cue", "generate"], "")]
    assert fake_log.claims == [Request(barmod.PRIORITY, {"input": getpass.getuser()})] and fake_log.authors[-1].name == getpass.getuser()


async def test_a_message_waits_for_the_turn_to_end_and_does_not_outrank_the_model(fake_log):
    fake_log.ask("first")
    sending = asyncio.create_task(barmod.send(fake_log, "second"))
    await asyncio.sleep(0.01)
    assert not sending.done() and barmod.PRIORITY <= 0  # a provider of the default priority is not cut short
    fake_log.say(["assistant"], "answer")
    await asyncio.wait_for(sending, 1)
    assert [content for _, content in said(fake_log)][-3:] == ["answer", "second", ""]


async def test_stop_outranks_any_provider_and_notes_it_without_asking_for_an_answer(fake_log):
    await barmod.stop(fake_log)
    assert said(fake_log) == [(["user", "stop"], "User stopped this response.")]
    assert fake_log.claims[0].priority == barmod.STOP_PRIORITY > 0


async def test_enter_sends_the_trimmed_line_and_clears_it_and_a_blank_line_is_not_sent(make):
    got = []
    bar, *_ = make(send=lambda log, text: recorder(got, log, text), busy=lambda log: False)
    type_(bar, "  hi  ")
    bar.on_key(b"\r")
    bar.on_key(b"\r")
    await settle(bar)
    assert got == ["hi"] and bar.editor.text == ""


async def test_a_line_starting_with_two_slashes_is_sent_without_the_first(make):
    got = []
    bar, *_ = make(send=lambda log, text: recorder(got, log, text), busy=lambda log: False)
    type_(bar, "//quit")
    bar.on_key(b"\r")
    await settle(bar)
    assert got == ["/quit"]


async def test_a_message_typed_while_the_model_is_busy_is_queued_and_the_line_is_cleared(make):
    got = []
    bar, *_ = make(send=lambda log, text: recorder(got, log, text), busy=lambda log: True)
    type_(bar, "next")
    bar.on_key(b"\r")
    assert bar.editor.text == "" and "queued" in bar.notice
    await settle(bar)
    assert got == ["next"]


async def test_messages_go_in_the_order_they_were_typed_and_a_failed_one_is_reported(make):
    got = []

    async def send(log, text):
        await asyncio.sleep(0.001)
        if text == "b":
            raise RuntimeError("boom")
        got.append(text)

    bar, *_ = make(send=send, busy=lambda log: False)
    for text in "abc":
        type_(bar, text)
        bar.on_key(b"\r")
    await settle(bar)
    assert got == ["a", "c"] and bar.notice == "not sent: 'b': boom" and not bar.outbox


# --- ctrl-c ---


async def test_ctrl_c_stops_a_busy_model_and_keeps_the_line(make):
    stopped = []

    async def stop(log):
        stopped.append(1)

    bar, *_ = make(busy=lambda log: True, stop=stop)
    type_(bar, "hi")
    bar.on_key(b"\x03")
    bar.on_key(b"\x03")  # once is enough: a second press while it stops does not stop again
    await settle(bar)
    assert stopped == [1] and bar.editor.text == "hi"


def test_ctrl_c_clears_the_line_when_nothing_is_working_and_ctrl_d_does_nothing(make):
    bar, *_ = make(busy=lambda log: False, stop=lambda log: pytest.fail("stopped"))
    type_(bar, "hi")
    bar.on_key(b"\x04")
    assert bar.editor.text == "hi"
    bar.on_key(b"\x03")
    assert bar.editor.text == ""


# --- commands ---


def test_quit_and_exit_end_the_session_and_an_unknown_command_is_reported_not_sent(make):
    bar, _, ended = make(send=lambda *a: pytest.fail("sent"))
    for line in ("/quit", "/exit"):
        type_(bar, line)
        bar.on_key(b"\r")
    assert ended == [1, 1] and bar.done
    bar.done = False
    type_(bar, "/nope")
    bar.on_key(b"\r")
    assert "unknown command /nope" in bar.notice


async def test_an_async_command_runs_beside_the_keyboard_and_its_failure_is_reported(make):
    from llvim.std.panels.input.commands import Command

    async def boom(ctx, arg):
        raise RuntimeError(f"no {arg}")

    bar, *_ = make(commands=[Command("boom", "fails", boom)])
    type_(bar, "/boom now")
    bar.on_key(b"\r")
    await settle(bar)
    assert bar.notice == "/boom failed: no now"


def test_typing_a_slash_opens_the_menu_and_tab_takes_the_only_match(make):
    bar, *_ = make()
    type_(bar, "/qu")
    assert [s.text for s in bar.menu.items] == ["/quit"]
    bar.on_key(b"\t")
    assert bar.editor.text == "/quit"


def test_tab_chooses_through_several_suggestions_and_enter_takes_the_chosen_one(make):
    bar, *_ = make(send=lambda *a: pytest.fail("sent"))
    type_(bar, "/")
    bar.on_key(b"\t")
    first = bar.menu.current().text
    bar.on_key(b"\x1b[B")
    assert bar.menu.current().text != first
    bar.on_key(b"\r")
    assert bar.editor.text.startswith("/") and not bar.done


def test_esc_closes_the_menu_until_the_line_changes(make):
    bar, *_ = make()
    type_(bar, "/q")
    bar.on_key(b"\x1b")
    assert not bar.menu.shown
    type_(bar, "u")
    assert bar.menu.shown


# --- other keys, and the screen ---


def test_a_paste_is_taken_as_text_with_its_line_breaks_and_without_sending(make):
    bar, *_ = make(send=lambda *a: pytest.fail("sent"))
    for raw in (b"\x1b[200~", b"a", b"\r", b"b", b"\x1b[201~"):
        bar.on_key(raw)
    assert bar.editor.text == "a\nb"


def test_page_keys_go_to_the_viewer_without_moving_the_focus_and_others_stay(make):
    bar, tmux, _ = make()
    bar.on_key(b"\x1b[5~")
    assert tmux.sent == [("%2", b"\x1b[5~")] and tmux.focused == []
    bar.on_key(b"\x1b[24~")
    assert len(tmux.sent) == 1


def test_drawing_asks_for_the_rows_the_menu_needs_and_shows_the_prompt(make, stub_screen):
    bar, *_ = make()
    type_(bar, "/")
    bar.draw()
    assert bar.growth.wanted[-1] == len(STANDARD) and stub_screen.drawn


async def test_the_bar_runs_until_a_command_ends_it(make, stub_screen):
    from llvim.std.panels.keys import Key

    bar, _, ended = make()
    stub_screen.events = [Key(c.encode()) for c in "/quit"] + [Key(b"\r")]
    bar._poke.set()
    await asyncio.wait_for(bar.run(), 1)
    assert ended == [1]


# --- the turn, with a model and a tool runner that act on cues ---


async def on_cue(log, channel, act):
    """Act each time `channel` is cued, as a provider or a tool runner does: claim, check the cue again, act."""
    async with aclosing(log.changes()) as changes:
        async for snapshot in changes:
            if cued(snapshot) == channel:
                async with await log.claim(Request(0, {"who": channel})) as writer:
                    if cued(log.read()) == channel:
                        await act(writer)


def model(replies):
    """Answers each GENERATE cue with the next reply. One that holds a call leaves a cue for the runner, after `pause`."""

    async def act(writer):
        text, call = replies.pop(0)
        writer.append(encode(["assistant"], text))
        if call:
            writer.append(encode(["tool_call"], call))
            while not writer.outranked() and not typed.is_set():
                await asyncio.sleep(0.001)
            await asyncio.sleep(0.02)  # the message typed meanwhile is waiting to claim
            writer.append(cue("tools"))
        await writer.commit()

    typed = asyncio.Event()
    return act, typed


async def runner(writer):
    writer.append(encode(["tool_result"], "a.txt"))
    writer.append(cue(GENERATE))
    await writer.commit()


async def test_a_message_typed_while_the_model_makes_calls_lands_after_the_calls_are_run_and_answered(fake_log):
    act, typed = model([("let me look", "ls"), ("there is a.txt", None)])
    programs = [asyncio.create_task(on_cue(fake_log, GENERATE, act)), asyncio.create_task(on_cue(fake_log, "tools", runner))]
    try:
        fake_log.ask("what is here?")
        while fake_log.holder() is None:
            await asyncio.sleep(0.001)
        sending = asyncio.create_task(barmod.send(fake_log, "typed mid-reply"))
        typed.set()
        await asyncio.wait_for(sending, 2)
    finally:
        for program in programs:
            program.cancel()
        await asyncio.gather(*programs, return_exceptions=True)
    assert [content or tags[-1] for tags, content in said(fake_log)] == [
        "what is here?", "generate",
        "let me look", "ls", "tools",
        "a.txt", "generate",
        "there is a.txt",
        "typed mid-reply", "generate",
    ]  # fmt: skip


async def test_a_queued_message_is_forced_in_by_ctrl_c_which_stops_the_model_where_it_is(fake_log, stub_screen, layout):
    turns = []

    async def endless(writer):
        """The first reply never ends by itself; the others are one word."""
        turns.append(1)
        reply = writer.append(encode(["assistant"], ""))
        while len(turns) == 1 and not writer.outranked():
            writer.extend(reply, b".")
            await asyncio.sleep(0.001)
        writer.extend(reply, b"ok" if len(turns) > 1 else b"")
        await writer.commit()

    panes, _ = layout()
    model_task = asyncio.create_task(on_cue(fake_log, GENERATE, endless))
    bar = Bar(fake_log, stub_screen, panes, StubGrowth(), commands=STANDARD)
    try:
        fake_log.ask("go on forever")
        while fake_log.holder() is None:
            await asyncio.sleep(0.001)
        for line in ("first", "second"):
            type_(bar, line)
            bar.on_key(b"\r")
        assert "queued" in bar.notice and len(bar.outbox) == 2
        await asyncio.sleep(0.02)
        assert len(bar.outbox) == 2  # the model never ends its turn by itself
        bar.on_key(b"\x03")
        await asyncio.wait_for(bar._sending, 2)
        # the stop overtook the cue, so the model is not asked again until the first queued message
        while fake_log.holder() is not None or cued(fake_log.read()) is not None:
            await asyncio.sleep(0.001)
    finally:
        model_task.cancel()
        await asyncio.gather(model_task, *bar._tasks, return_exceptions=True)
    tail = [(tags, content.strip(".") if tags == ["assistant"] else content) for tags, content in said(fake_log)][2:]
    assert tail[:2] == [(["assistant"], ""), (["user", "stop"], barmod.STOPPED)]
    assert [content for tags, content in tail if tags != ["cue", "generate"]][2:] == ["first", "ok", "second", "ok"]


async def test_a_continue_typed_while_the_model_works_is_queued_in_order_with_the_messages(fake_log, stub_screen, layout):
    panes, _ = layout()
    bar = Bar(fake_log, stub_screen, panes, StubGrowth(), commands=STANDARD)
    fake_log.ask("first question")
    fake_log.hold(Request(0, {"provider": "openai"}))
    for line in ("/continue", "then this"):
        type_(bar, line)
        bar.on_key(b"\r")
    assert [label for label, _ in bar.outbox] == ["/continue", "then this"] and "queued" in bar.notice
    fake_log.say(["assistant"], "answer")
    fake_log.hold(None)  # the turn is over; nobody answers the cues in this test, so each waits for the next
    while cued(fake_log.read()) is None:
        await asyncio.sleep(0.001)
    assert said(fake_log)[-2:] == [(["assistant"], "answer"), (["cue", "generate"], "")]
    assert [label for label, _ in bar.outbox] == ["then this"]  # it waits for the model to answer the continue
    fake_log.say(["assistant"], "went on")  # the model answers /continue
    await asyncio.wait_for(bar._sending, 1)
    assert [c for _, c in said(fake_log)][-4:] == ["", "went on", "then this", ""]
